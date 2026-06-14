// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.

//! ActPlane — OS-level agent harness.
//!
//! Loads an `actplane.yaml` project policy, lowers its embedded taint DSL to the
//! kernel ABI, runs the embedded eBPF engine, and reports every kernel-detected
//! rule match with the corrective-feedback payload.

use clap::{Args, Parser, Subcommand, ValueEnum};
use std::ffi::OsString;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

mod audit;
mod config;
mod control;
mod doctor;
mod dsl;
mod feedback;
mod hook;
mod mcp;
mod report;
mod runtime;
mod setup;
mod template_generate;
mod templates;

type AnyError = Box<dyn std::error::Error + Send + Sync>;
type Result<T> = std::result::Result<T, AnyError>;

#[derive(Parser)]
#[command(author, version, about = "ActPlane: OS-level agent harness", long_about = None,
    after_help = "EXAMPLES:\n  \
      # get started: write a starter policy, wire agent hooks/MCP, then diagnose\n  \
      actplane init  &&  actplane doctor\n\n  \
      # inspect or write a built-in policy template\n  \
      actplane templates list\n  \
      actplane templates write no-git-branch --format dsl --out /tmp/no-git-branch.dsl\n\n  \
      # generate a template policy and its static review artifact in one step\n  \
      actplane templates review no-secret-egress --policy-out /tmp/no-secret-policy.yaml --review-out /tmp/no-secret-review.txt\n\n  \
      # infer a candidate policy from project instructions and manifests\n  \
      actplane templates generate --policy-out /tmp/actplane-candidate.yaml --review-out /tmp/actplane-candidate-review.txt\n\n  \
      # plan observe-first rollout for the selected policy\n  \
      actplane --policy actplane.yaml rollout --out docs/actplane-rollout.txt --observe-policy-out /tmp/actplane-observe.yaml\n\n  \
      # after an observe run, include event logs for promotion guidance\n  \
      actplane --policy actplane.yaml rollout --events .actplane/events.jsonl\n\n  \
      # apply a one-line policy around a command (needs sudo for the eBPF load)\n  \
      sudo -E actplane --rule 'source COMMAND = exec \"**\"\n                       rule no-git-branch:\n                         kill exec \"git\" \"branch\" if COMMAND\n                         because \"create a branch via the host, not the agent\"' run claude -p '...'\n\n  \
      # use a project policy file (auto-discovered as ./actplane.yaml upward)\n  \
      sudo -E actplane run <your agent command>\n\n  \
      # serve MCP resources and auto-attach to the parent agent when Codex starts it\n  \
      actplane mcp --auto-attach-parent\n\n  \
      # just compile/validate a policy (no privileges needed)\n  \
      actplane --policy actplane.yaml compile --out /tmp/policy.bin\n\n  \
      # attach to the parent agent/shell and report violations without launching a child\n  \
      actplane --policy actplane.yaml watch\n\n  \
      # append a scoped runtime delta to an already-running watch/MCP engine\n  \
      actplane delta add --target-id <domain-id> --delta policy-delta.dsl\n\n\
    See docs/rule-language.md for the policy language.")]
pub(crate) struct Cli {
    /// Project policy YAML. Defaults to discovering actplane.yaml upward from cwd.
    #[arg(long, global = true, conflicts_with = "rule")]
    pub(crate) policy: Option<PathBuf>,
    /// Inline policy DSL used instead of a YAML file.
    #[arg(long, global = true, conflicts_with = "policy")]
    pub(crate) rule: Option<String>,
    /// Domain to compile/run from a policy file with `domains:`.
    #[arg(long, global = true, conflicts_with = "rule")]
    pub(crate) domain: Option<String>,
    /// Run the target command as root. By default sudo-launched ActPlane drops
    /// the target back to SUDO_UID/SUDO_GID.
    #[arg(long, global = true)]
    pub(crate) run_as_root: bool,
    /// Internal flag: set by auto-elevation to prevent recursive sudo.
    #[arg(long, global = true, hide = true)]
    pub(crate) internal_elevated: bool,
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Run a command under the policy harness.
    Run {
        #[arg(required = true, trailing_var_arg = true, allow_hyphen_values = true)]
        cmd: Vec<String>,
    },
    /// Run a command as a child runtime policy domain.
    #[command(name = "child-run")]
    ChildRun(ChildRunArgs),
    /// Compile the policy to the kernel config blob.
    Compile {
        #[arg(short, long)]
        out: PathBuf,
    },
    /// Write a starter actplane.yaml (commented guardrail template) in the cwd.
    Init {
        /// Overwrite an existing actplane.yaml.
        #[arg(short, long)]
        force: bool,
    },
    /// Wire project-local Codex hooks, MCP config, and AGENTS.md.
    Setup {
        /// Overwrite ActPlane-managed project integration files.
        #[arg(short, long)]
        force: bool,
    },
    /// Validate the policy (no privileges): compile it, summarize each rule in
    /// plain language, and warn about anything that won't apply as written.
    Check(CheckArgs),
    /// Produce an observe-first rollout plan for the selected policy.
    Rollout(RolloutArgs),
    /// Diagnose policy discovery, kernel support, feedback hooks, and MCP setup.
    Doctor,
    /// List policy domains and their effective locked/default rules.
    Domains,
    /// Load the policy and report violations without starting a child command.
    Watch,
    /// Hook adapter: forward new feedback-file bytes as agent additionalContext.
    FeedbackHook,
    /// Run as an MCP (Model Context Protocol) server over stdio.
    Mcp {
        /// On startup, load the eBPF engine and seed the parent process.
        #[arg(long)]
        auto_attach_parent: bool,
    },
    /// Control an already-running auto-attached ActPlane engine.
    Control {
        #[command(subcommand)]
        command: ControlCommands,
    },
    /// Manage runtime policy deltas through the repo-local control socket.
    Delta {
        #[command(subcommand)]
        command: DeltaCommands,
    },
    /// List, inspect, and write built-in policy templates.
    Templates {
        #[command(subcommand)]
        command: TemplateCommands,
    },
}

#[derive(Args)]
struct ChildRunArgs {
    /// Optional runtime domain id for the child. Defaults to the launched pid.
    #[arg(long)]
    child_id: Option<u32>,
    /// Optional narrower scope id for the child domain.
    #[arg(long, default_value_t = 0)]
    scope_id: u32,
    /// Append-only ActPlane DSL fragment file installed into the child before resume.
    #[arg(long = "delta", value_name = "FILE")]
    deltas: Vec<PathBuf>,
    /// Inline append-only ActPlane DSL fragment installed into the child before resume.
    #[arg(long = "delta-text", value_name = "DSL")]
    delta_text: Vec<String>,
    /// Optional approval metadata for child policy deltas.
    #[arg(long)]
    approved_by: Option<String>,
    /// Optional ticket, review, or decision id for child policy deltas.
    #[arg(long)]
    approval_ref: Option<String>,
    /// Optional tool or agent identity that generated child policy deltas.
    #[arg(long)]
    generated_by: Option<String>,
    /// Child command argv.
    #[arg(required = true, trailing_var_arg = true, allow_hyphen_values = true)]
    cmd: Vec<String>,
}

#[derive(Args)]
struct CheckArgs {
    /// Emit a stable machine-readable support matrix and warning report.
    #[arg(long)]
    json: bool,
    /// Emit a human-readable policy review explaining enforcement timing and limits.
    #[arg(long, conflicts_with = "json")]
    explain: bool,
    /// Write the --explain policy review artifact to a file instead of stdout.
    #[arg(
        long,
        value_name = "FILE",
        requires = "explain",
        conflicts_with = "json"
    )]
    out: Option<PathBuf>,
    /// Overwrite an existing --out policy review artifact.
    #[arg(long, requires = "out")]
    force: bool,
}

#[derive(Args)]
struct RolloutArgs {
    /// Write the rollout plan artifact to a file instead of stdout.
    #[arg(long, value_name = "FILE")]
    out: Option<PathBuf>,
    /// Write a notify-only observe-first YAML policy for the selected policy/domain.
    #[arg(long, value_name = "FILE")]
    observe_policy_out: Option<PathBuf>,
    /// Read observe-mode violation JSONL events and include event-backed promotion guidance.
    #[arg(long = "events", value_name = "FILE")]
    events: Vec<PathBuf>,
    /// Overwrite existing rollout output files.
    #[arg(short, long)]
    force: bool,
}

#[derive(Subcommand)]
enum ControlCommands {
    /// Show the currently reachable local control server.
    Status,
    /// Hot-reload actplane.yaml into the already-running engine.
    ReloadPolicy,
    /// Bind an already-started subagent root pid to a child runtime domain.
    BindChild {
        /// Linux pid of the subagent root process.
        #[arg(long)]
        pid: i32,
        /// Optional runtime domain id. Defaults to pid.
        #[arg(long)]
        child_id: Option<u32>,
        /// Optional narrower scope id.
        #[arg(long, default_value_t = 0)]
        scope_id: u32,
    },
    /// Append an ActPlane DSL delta to an existing runtime domain.
    AppendDelta(DeltaAddArgs),
    /// Launch a stopped child process in the running engine, attach policy, then resume.
    LaunchChild {
        /// Optional runtime domain id. Defaults to the launched pid.
        #[arg(long)]
        child_id: Option<u32>,
        /// Optional narrower scope id.
        #[arg(long, default_value_t = 0)]
        scope_id: u32,
        /// ActPlane DSL fragment file installed before resume.
        #[arg(long = "delta", value_name = "FILE")]
        deltas: Vec<PathBuf>,
        /// Inline ActPlane DSL fragment installed before resume.
        #[arg(long = "delta-text", value_name = "DSL")]
        delta_text: Vec<String>,
        /// Relaunch policy for reconciliation: never or on_exit.
        #[arg(long, default_value = "never")]
        restart_policy: String,
        /// Maximum automatic relaunches for this child lineage.
        #[arg(long, default_value_t = 3)]
        restart_limit: u32,
        /// Delay before automatic relaunch after exit, in milliseconds.
        #[arg(long, default_value_t = 1000)]
        restart_backoff_ms: u64,
        /// Optional approval metadata for child policy deltas.
        #[arg(long)]
        approved_by: Option<String>,
        /// Optional ticket, review, or decision id for child policy deltas.
        #[arg(long)]
        approval_ref: Option<String>,
        /// Optional tool or agent identity that generated child policy deltas.
        #[arg(long)]
        generated_by: Option<String>,
        /// Child command argv.
        #[arg(required = true, trailing_var_arg = true, allow_hyphen_values = true)]
        cmd: Vec<String>,
    },
    /// List child domains known to the running control server.
    ListChildren,
    /// Read detached stdout/stderr logs for a launched child domain.
    ReadLogs {
        /// Child runtime domain id.
        #[arg(long, conflicts_with = "domain_id")]
        child_id: Option<u32>,
        /// Alias for --child-id.
        #[arg(long, conflicts_with = "child_id")]
        domain_id: Option<u32>,
        /// stdout, stderr, or both.
        #[arg(long, default_value = "both")]
        stream: String,
        /// Maximum bytes to return per stream.
        #[arg(long, default_value_t = 8192)]
        max_bytes: usize,
    },
    /// Terminate the process group for a launched child domain.
    TerminateChild {
        /// Child runtime domain id.
        #[arg(long, conflicts_with = "domain_id")]
        child_id: Option<u32>,
        /// Alias for --child-id.
        #[arg(long, conflicts_with = "child_id")]
        domain_id: Option<u32>,
    },
    /// Restart a launched child domain in a fresh runtime domain.
    RestartChild {
        /// Existing child runtime domain id.
        #[arg(long, conflicts_with = "domain_id")]
        child_id: Option<u32>,
        /// Alias for --child-id.
        #[arg(long, conflicts_with = "child_id")]
        domain_id: Option<u32>,
        /// Optional fresh runtime domain id. Defaults to the new pid.
        #[arg(long)]
        new_child_id: Option<u32>,
        /// Terminate the existing process group first if it is still running.
        #[arg(long)]
        terminate_existing: bool,
    },
    /// Reconcile child registry state against live Linux processes.
    ReconcileChildren,
}

#[derive(Subcommand)]
enum DeltaCommands {
    /// Append an ActPlane DSL delta to an existing runtime domain.
    Add(DeltaAddArgs),
}

#[derive(Subcommand)]
enum TemplateCommands {
    /// List built-in policy templates.
    List {
        /// Emit machine-readable template metadata.
        #[arg(long)]
        json: bool,
    },
    /// Print one built-in template.
    Show(TemplateShowArgs),
    /// Write one built-in template to a file.
    Write(TemplateWriteArgs),
    /// Write one YAML template and its policy review artifact.
    Review(TemplateReviewArgs),
    /// Infer a candidate policy from project instructions and manifests.
    Generate(TemplateGenerateArgs),
}

#[derive(Args)]
struct TemplateShowArgs {
    /// Template id, for example `no-secret-egress`.
    name: String,
    /// Output format.
    #[arg(long, value_enum, default_value_t = TemplateFormat::Dsl)]
    format: TemplateFormat,
    /// Override a declared template parameter, as key=value. Repeat for multiple parameters.
    #[arg(long = "set", value_name = "KEY=VALUE")]
    params: Vec<String>,
}

#[derive(Args)]
struct TemplateWriteArgs {
    /// Template id, for example `no-secret-egress`.
    name: String,
    /// Output file path.
    #[arg(short, long)]
    out: PathBuf,
    /// Output format.
    #[arg(long, value_enum, default_value_t = TemplateFormat::Yaml)]
    format: TemplateFormat,
    /// Override a declared template parameter, as key=value. Repeat for multiple parameters.
    #[arg(long = "set", value_name = "KEY=VALUE")]
    params: Vec<String>,
    /// Overwrite an existing output file.
    #[arg(short, long)]
    force: bool,
}

#[derive(Args)]
struct TemplateReviewArgs {
    /// Template id, for example `no-secret-egress`.
    name: String,
    /// Output YAML policy file path.
    #[arg(long, value_name = "FILE")]
    policy_out: PathBuf,
    /// Output human-readable policy review file path.
    #[arg(long, value_name = "FILE")]
    review_out: PathBuf,
    /// Override a declared template parameter, as key=value. Repeat for multiple parameters.
    #[arg(long = "set", value_name = "KEY=VALUE")]
    params: Vec<String>,
    /// Overwrite existing output files.
    #[arg(short, long)]
    force: bool,
}

#[derive(Args)]
struct TemplateGenerateArgs {
    /// Instruction file to inspect. Defaults to project AGENTS.md/CLAUDE.md.
    #[arg(long = "instructions", value_name = "FILE")]
    instructions: Vec<PathBuf>,
    /// Optional task hint to include in template selection.
    #[arg(long)]
    task: Option<String>,
    /// Output YAML candidate policy file path.
    #[arg(long, value_name = "FILE")]
    policy_out: PathBuf,
    /// Output human-readable policy review file path.
    #[arg(long, value_name = "FILE")]
    review_out: PathBuf,
    /// Overwrite existing output files.
    #[arg(short, long)]
    force: bool,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum TemplateFormat {
    Dsl,
    Yaml,
}

#[derive(Args)]
struct DeltaAddArgs {
    /// Runtime domain id to receive the delta. Defaults to the attached parent domain.
    #[arg(long, conflicts_with = "domain_id")]
    target_id: Option<u32>,
    /// Alias for --target-id.
    #[arg(long, conflicts_with = "target_id")]
    domain_id: Option<u32>,
    /// ActPlane DSL fragment file.
    #[arg(long = "delta", value_name = "FILE")]
    deltas: Vec<PathBuf>,
    /// Inline ActPlane DSL fragment.
    #[arg(long = "delta-text", value_name = "DSL")]
    delta_text: Vec<String>,
    /// Optional approval metadata for this delta.
    #[arg(long)]
    approved_by: Option<String>,
    /// Optional ticket, review, or decision id for this delta.
    #[arg(long)]
    approval_ref: Option<String>,
    /// Optional tool or agent identity that generated this delta.
    #[arg(long)]
    generated_by: Option<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let cli = Cli::parse();

    let code = match &cli.command {
        Commands::Run { cmd } => runtime::run_command(&cli, cmd).await?,
        Commands::ChildRun(args) => {
            let audit_meta = policy_audit_meta_from_fields(
                None,
                &args.approved_by,
                &args.approval_ref,
                &args.generated_by,
            );
            runtime::run_child_command(
                &cli,
                args.child_id,
                args.scope_id,
                &args.deltas,
                &args.delta_text,
                &audit_meta,
                &args.cmd,
            )
            .await?
        }
        Commands::Compile { out } => compile_policy(&cli, out).await?,
        Commands::Init { force } => setup::init_policy(*force)?,
        Commands::Setup { force } => setup::setup_project(*force)?,
        Commands::Check(args) => doctor::check_policy(
            &cli,
            args.json,
            args.explain,
            args.out.as_deref(),
            args.force,
        )?,
        Commands::Rollout(args) => rollout_command(args, &cli)?,
        Commands::Doctor => doctor::doctor(&cli)?,
        Commands::Domains => doctor::list_domains(&cli)?,
        Commands::Watch => runtime::watch_policy(&cli).await?,
        Commands::FeedbackHook => {
            hook::feedback_hook().await?;
            0
        }
        Commands::Mcp { auto_attach_parent } => {
            let attach = if *auto_attach_parent {
                Some(runtime::start_mcp_auto_attach(&cli)?)
            } else {
                None
            };
            let control = attach.as_ref().and_then(|a| a.engine_control());
            mcp::run_mcp_server_with_control(control, Some(control_project_dir(&cli)?)).await?;
            drop(attach);
            0
        }
        Commands::Control { command } => control_command(&cli, command).await?,
        Commands::Delta { command } => delta_command(&cli, command).await?,
        Commands::Templates { command } => template_command(&cli, command)?,
    };
    if code != 0 {
        std::process::exit(code);
    }
    Ok(())
}

fn rollout_command(args: &RolloutArgs, cli: &Cli) -> Result<i32> {
    let artifacts = doctor::render_rollout_artifacts(cli, &args.events)?;
    match (&args.out, &args.observe_policy_out) {
        (Some(plan_path), Some(observe_path)) => {
            write_pair_output_files(
                plan_path,
                &artifacts.plan,
                observe_path,
                &artifacts.observe_policy_yaml,
                args.force,
                "--out and --observe-policy-out must be different",
            )?;
            eprintln!("actplane: wrote rollout plan {}", plan_path.display());
            eprintln!(
                "actplane: wrote observe-first policy {}",
                observe_path.display()
            );
        }
        (Some(plan_path), None) => {
            write_output_file(plan_path, &artifacts.plan, args.force)?;
            eprintln!("actplane: wrote rollout plan {}", plan_path.display());
        }
        (None, Some(observe_path)) => {
            write_output_file(observe_path, &artifacts.observe_policy_yaml, args.force)?;
            eprintln!(
                "actplane: wrote observe-first policy {}",
                observe_path.display()
            );
            print!("{}", artifacts.plan);
        }
        (None, None) => print!("{}", artifacts.plan),
    }
    Ok(0)
}

fn template_command(cli: &Cli, command: &TemplateCommands) -> Result<i32> {
    if cli.policy.is_some() || cli.rule.is_some() || cli.domain.is_some() {
        return Err(
            "`actplane templates` does not read --policy, --rule, or --domain; use `actplane check` to review an existing policy"
                .into(),
        );
    }
    match command {
        TemplateCommands::List { json } => {
            if *json {
                println!("{}", serde_json::to_string_pretty(&templates::json())?);
            } else {
                println!("ActPlane policy templates");
                for template in templates::all() {
                    println!(
                        "  {:<24} {:<12} {:<6} {}",
                        template.id, template.category, template.effect, template.title
                    );
                }
                println!("\nUse `actplane templates show <id>` to inspect DSL.");
            }
        }
        TemplateCommands::Show(args) => {
            let template = templates::get(&args.name)?;
            print!("{}", render_template(template, args.format, &args.params)?);
        }
        TemplateCommands::Write(args) => {
            let template = templates::get(&args.name)?;
            write_output_file(
                &args.out,
                &render_template(template, args.format, &args.params)?,
                args.force,
            )?;
            eprintln!(
                "actplane: wrote template `{}` to {}",
                template.id,
                args.out.display()
            );
        }
        TemplateCommands::Review(args) => {
            let template = templates::get(&args.name)?;
            let policy_yaml = templates::render_yaml(template, &args.params)?;
            let review = render_policy_review_for_yaml(
                &policy_yaml,
                &args.policy_out,
                &format!("template `{}` generated invalid YAML", template.id),
            )?;
            write_pair_output_files(
                &args.policy_out,
                &policy_yaml,
                &args.review_out,
                &review,
                args.force,
                "--policy-out and --review-out must be different",
            )?;
            eprintln!(
                "actplane: wrote template `{}` to {}",
                template.id,
                args.policy_out.display()
            );
            eprintln!(
                "actplane: wrote policy review {}",
                args.review_out.display()
            );
        }
        TemplateCommands::Generate(args) => {
            let root = template_project_root()?;
            let generated =
                template_generate::generate(&root, &args.instructions, args.task.as_deref())?;
            let policy_yaml = template_generate::render_yaml(&generated)?;
            let review = render_policy_review_for_yaml(
                &policy_yaml,
                &args.policy_out,
                "generated candidate policy is invalid YAML",
            )?;
            write_pair_output_files(
                &args.policy_out,
                &policy_yaml,
                &args.review_out,
                &review,
                args.force,
                "--policy-out and --review-out must be different",
            )?;
            eprintln!(
                "actplane: generated {} template-backed policy rule set(s)",
                generated.templates.len()
            );
            for line in template_generate::summary(&generated) {
                eprintln!("actplane: selected {line}");
            }
            eprintln!(
                "actplane: wrote candidate policy {}",
                args.policy_out.display()
            );
            eprintln!(
                "actplane: wrote policy review {}",
                args.review_out.display()
            );
        }
    }
    Ok(0)
}

fn write_output_file(path: &Path, contents: &str, force: bool) -> Result<()> {
    preflight_output_file(path, force)?;
    std::fs::write(path, contents)?;
    Ok(())
}

fn write_pair_output_files(
    first_path: &Path,
    first_contents: &str,
    second_path: &Path,
    second_contents: &str,
    force: bool,
    same_path_error: &str,
) -> Result<()> {
    let first_key = preflight_output_file(first_path, force)?;
    let second_key = preflight_output_file(second_path, force)?;
    if first_key == second_key {
        return Err(same_path_error.to_string().into());
    }

    let first_tmp = write_temp_output(first_path, first_contents)?;
    let second_tmp = write_temp_output(second_path, second_contents)?;

    let mut backups = Vec::new();
    match backup_existing_output(first_path) {
        Ok(backup) => backups.push((first_path.to_path_buf(), backup)),
        Err(e) => return Err(e),
    }
    match backup_existing_output(second_path) {
        Ok(backup) => backups.push((second_path.to_path_buf(), backup)),
        Err(e) => {
            restore_output_backups(&backups);
            return Err(e);
        }
    }

    if let Err(e) = persist_temp_output(first_tmp, first_path) {
        restore_output_backups(&backups);
        return Err(e);
    }
    if let Err(e) = persist_temp_output(second_tmp, second_path) {
        let _ = std::fs::remove_file(first_path);
        restore_output_backups(&backups);
        return Err(e);
    }
    remove_output_backups(&backups);
    Ok(())
}

fn write_temp_output(path: &Path, contents: &str) -> Result<tempfile::NamedTempFile> {
    let mut file = tempfile::Builder::new()
        .prefix(".actplane-output-")
        .tempfile_in(output_parent(path))?;
    file.write_all(contents.as_bytes())?;
    file.flush()?;
    file.as_file().sync_all()?;
    Ok(file)
}

fn persist_temp_output(file: tempfile::NamedTempFile, path: &Path) -> Result<()> {
    file.persist(path)
        .map(|_| ())
        .map_err(|e| format!("writing {}: {}", path.display(), e.error).into())
}

fn backup_existing_output(path: &Path) -> Result<Option<PathBuf>> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => {
            let backup = unique_backup_path(path)?;
            std::fs::rename(path, &backup).map_err(|e| {
                format!(
                    "preparing backup for {} at {}: {}",
                    path.display(),
                    backup.display(),
                    e
                )
            })?;
            Ok(Some(backup))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("reading metadata for {}: {}", path.display(), e).into()),
    }
}

fn unique_backup_path(path: &Path) -> Result<PathBuf> {
    let file_name = path
        .file_name()
        .ok_or_else(|| format!("{} is not a valid output file path", path.display()))?;
    for attempt in 0..1000u32 {
        let mut name = OsString::from(format!(
            ".actplane-backup-{}-{attempt}-",
            std::process::id()
        ));
        name.push(file_name);
        let candidate = output_parent(path).join(name);
        match std::fs::symlink_metadata(&candidate) {
            Ok(_) => continue,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(candidate),
            Err(e) => {
                return Err(format!("reading metadata for {}: {}", candidate.display(), e).into());
            }
        }
    }
    Err(format!("could not allocate a backup path for {}", path.display()).into())
}

fn restore_output_backups(backups: &[(PathBuf, Option<PathBuf>)]) {
    for (target, backup) in backups.iter().rev() {
        if let Some(backup) = backup {
            let _ = std::fs::remove_file(target);
            let _ = std::fs::rename(backup, target);
        }
    }
}

fn remove_output_backups(backups: &[(PathBuf, Option<PathBuf>)]) {
    for (_, backup) in backups {
        if let Some(backup) = backup {
            let _ = std::fs::remove_file(backup);
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
enum OutputPathKey {
    #[cfg(unix)]
    ExistingFile {
        dev: u64,
        ino: u64,
    },
    Path(PathBuf),
}

fn preflight_output_file(path: &Path, force: bool) -> Result<OutputPathKey> {
    match std::fs::symlink_metadata(path) {
        Ok(meta) => {
            if meta.file_type().is_symlink() {
                return Err(format!(
                    "{} is a symlink; use the resolved target path instead",
                    path.display()
                )
                .into());
            }
            if meta.is_dir() {
                return Err(
                    format!("{} is a directory, not an output file", path.display()).into(),
                );
            }
            if !meta.is_file() {
                return Err(format!("{} is not a regular output file", path.display()).into());
            }
            if !force {
                return Err(format!(
                    "{} already exists (use --force to overwrite)",
                    path.display()
                )
                .into());
            }
            #[cfg(unix)]
            {
                return Ok(OutputPathKey::ExistingFile {
                    dev: meta.dev(),
                    ino: meta.ino(),
                });
            }
            #[cfg(not(unix))]
            {
                return Ok(OutputPathKey::Path(std::fs::canonicalize(path)?));
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => {
            return Err(format!("reading metadata for {}: {}", path.display(), e).into());
        }
    }

    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    if !parent.is_dir() {
        return Err(format!(
            "parent directory for {} does not exist or is not a directory",
            path.display()
        )
        .into());
    }
    let file_name = path
        .file_name()
        .ok_or_else(|| format!("{} is not a valid output file path", path.display()))?;
    Ok(OutputPathKey::Path(
        std::fs::canonicalize(parent)?.join(file_name),
    ))
}

fn output_parent(path: &Path) -> &Path {
    path.parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
}

fn template_project_root() -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    if let Some(policy) = config::discover_policy(&cwd) {
        return Ok(policy
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| cwd.clone()));
    }
    let mut dir = Some(cwd.as_path());
    while let Some(candidate) = dir {
        if candidate.join(".git").exists() {
            return Ok(candidate.to_path_buf());
        }
        dir = candidate.parent();
    }
    Ok(cwd)
}

fn render_policy_review_for_yaml(
    policy_yaml: &str,
    policy_path: &Path,
    yaml_error_context: &str,
) -> Result<String> {
    let config: config::FileConfig =
        serde_yaml::from_str(policy_yaml).map_err(|e| format!("{yaml_error_context}: {e}"))?;
    let loaded = config::LoadedPolicy {
        config,
        root: std::env::current_dir()?,
        path: Some(policy_path.to_path_buf()),
    };
    doctor::render_policy_review_for_loaded(&loaded, None)
}

fn render_template(
    template: &templates::PolicyTemplate,
    format: TemplateFormat,
    params: &[String],
) -> Result<String> {
    match format {
        TemplateFormat::Dsl => templates::render_dsl(template, params),
        TemplateFormat::Yaml => templates::render_yaml(template, params),
    }
}

async fn control_command(cli: &Cli, command: &ControlCommands) -> Result<i32> {
    let project_dir = control_project_dir(cli)?;
    let responses = match command {
        ControlCommands::Status => {
            vec![control::send_request(
                &project_dir,
                serde_json::json!({ "op": "status" }),
            )?]
        }
        ControlCommands::ReloadPolicy => vec![control::send_request(
            &project_dir,
            serde_json::json!({ "op": "reload_policy" }),
        )?],
        ControlCommands::BindChild {
            pid,
            child_id,
            scope_id,
        } => {
            let mut request = serde_json::json!({
                "op": "bind_child_domain",
                "pid": pid,
                "scope_id": scope_id,
            });
            if let Some(child_id) = child_id {
                request["child_id"] = serde_json::json!(child_id);
            }
            vec![control::send_request(&project_dir, request)?]
        }
        ControlCommands::AppendDelta(args) => {
            append_delta_control_requests(&project_dir, args, "control append-delta")?
        }
        ControlCommands::LaunchChild {
            child_id,
            scope_id,
            deltas,
            delta_text,
            restart_policy,
            restart_limit,
            restart_backoff_ms,
            approved_by,
            approval_ref,
            generated_by,
            cmd,
        } => {
            let policy =
                join_policy_delta_fragments(load_policy_delta_fragments(deltas, delta_text)?);
            let mut request = serde_json::json!({
                "op": "launch_child_domain",
                "cmd": cmd,
                "scope_id": scope_id,
                "restart_policy": restart_policy,
                "restart_limit": restart_limit,
                "restart_backoff_ms": restart_backoff_ms,
            });
            if let Some(child_id) = child_id {
                request["child_id"] = serde_json::json!(child_id);
            }
            add_policy_audit_meta_fields(
                &mut request,
                &policy_audit_meta_from_fields(None, approved_by, approval_ref, generated_by),
            );
            if let Some(policy) = policy {
                request["policy"] = serde_json::json!(policy);
            }
            vec![control::send_request(&project_dir, request)?]
        }
        ControlCommands::ListChildren => vec![control::send_request(
            &project_dir,
            serde_json::json!({ "op": "list_child_domains" }),
        )?],
        ControlCommands::ReadLogs {
            child_id,
            domain_id,
            stream,
            max_bytes,
        } => {
            let child_id = child_id
                .or(*domain_id)
                .ok_or("control read-logs requires --child-id or --domain-id")?;
            vec![control::send_request(
                &project_dir,
                serde_json::json!({
                    "op": "read_child_domain_logs",
                    "child_id": child_id,
                    "stream": stream,
                    "max_bytes": max_bytes,
                }),
            )?]
        }
        ControlCommands::TerminateChild {
            child_id,
            domain_id,
        } => {
            let child_id = child_id
                .or(*domain_id)
                .ok_or("control terminate-child requires --child-id or --domain-id")?;
            vec![control::send_request(
                &project_dir,
                serde_json::json!({
                    "op": "terminate_child_domain",
                    "child_id": child_id,
                }),
            )?]
        }
        ControlCommands::RestartChild {
            child_id,
            domain_id,
            new_child_id,
            terminate_existing,
        } => {
            let child_id = child_id
                .or(*domain_id)
                .ok_or("control restart-child requires --child-id or --domain-id")?;
            let mut request = serde_json::json!({
                "op": "restart_child_domain",
                "child_id": child_id,
                "terminate_existing": terminate_existing,
            });
            if let Some(new_child_id) = new_child_id {
                request["new_child_id"] = serde_json::json!(new_child_id);
            }
            vec![control::send_request(&project_dir, request)?]
        }
        ControlCommands::ReconcileChildren => vec![control::send_request(
            &project_dir,
            serde_json::json!({ "op": "reconcile_child_domains" }),
        )?],
    };
    for response in responses {
        print_control_response(response)?;
    }
    Ok(0)
}

async fn delta_command(cli: &Cli, command: &DeltaCommands) -> Result<i32> {
    let project_dir = control_project_dir(cli)?;
    let responses = match command {
        DeltaCommands::Add(args) => append_delta_control_requests(&project_dir, args, "delta add")?,
    };
    for response in responses {
        print_control_response(response)?;
    }
    Ok(0)
}

fn append_delta_control_requests(
    project_dir: &Path,
    args: &DeltaAddArgs,
    command_name: &str,
) -> Result<Vec<serde_json::Value>> {
    let target_id = args.target_id.or(args.domain_id);
    let policies = load_policy_delta_fragments(&args.deltas, &args.delta_text)?;
    if policies.is_empty() {
        return Err(format!("{command_name} requires --delta or --delta-text").into());
    }
    let mut responses = Vec::new();
    for (policy_ref, policy) in policies {
        let mut request = serde_json::json!({
            "op": "append_policy_delta",
            "policy": policy,
            "policy_ref": policy_ref,
        });
        add_policy_audit_meta_fields(&mut request, &policy_audit_meta_from_delta_args(args));
        if let Some(target_id) = target_id {
            request["target_id"] = serde_json::json!(target_id);
        }
        responses.push(control::send_request(project_dir, request)?);
    }
    Ok(responses)
}

fn policy_audit_meta_from_delta_args(args: &DeltaAddArgs) -> runtime::PolicyAuditMeta {
    policy_audit_meta_from_fields(
        None,
        &args.approved_by,
        &args.approval_ref,
        &args.generated_by,
    )
}

fn policy_audit_meta_from_fields(
    policy_ref: Option<String>,
    approved_by: &Option<String>,
    approval_ref: &Option<String>,
    generated_by: &Option<String>,
) -> runtime::PolicyAuditMeta {
    runtime::PolicyAuditMeta {
        policy_ref,
        approved_by: approved_by.clone(),
        approval_ref: approval_ref.clone(),
        generated_by: generated_by.clone(),
    }
}

fn add_policy_audit_meta_fields(request: &mut serde_json::Value, meta: &runtime::PolicyAuditMeta) {
    if let Some(policy_ref) = &meta.policy_ref {
        request["policy_ref"] = serde_json::json!(policy_ref);
    }
    if let Some(approved_by) = &meta.approved_by {
        request["approved_by"] = serde_json::json!(approved_by);
    }
    if let Some(approval_ref) = &meta.approval_ref {
        request["approval_ref"] = serde_json::json!(approval_ref);
    }
    if let Some(generated_by) = &meta.generated_by {
        request["generated_by"] = serde_json::json!(generated_by);
    }
}

fn control_project_dir(cli: &Cli) -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    if let Some(policy) = &cli.policy {
        let path = config::absolutize(policy, &cwd);
        return Ok(path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| cwd.clone()));
    }
    if let Some(policy) = config::discover_policy(&cwd) {
        return Ok(policy
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| cwd.clone()));
    }
    Ok(cwd)
}

fn load_policy_delta_fragments(
    paths: &[PathBuf],
    inline: &[String],
) -> Result<Vec<(String, String)>> {
    let mut deltas = Vec::new();
    for path in paths {
        let src = std::fs::read_to_string(path)
            .map_err(|e| format!("cannot read policy delta {}: {e}", path.display()))?;
        deltas.push((path.display().to_string(), src));
    }
    for (idx, src) in inline.iter().enumerate() {
        deltas.push((format!("--delta-text[{idx}]"), src.clone()));
    }
    Ok(deltas)
}

fn join_policy_delta_fragments(deltas: Vec<(String, String)>) -> Option<String> {
    if deltas.is_empty() {
        return None;
    }
    let mut out = String::new();
    for (policy_ref, src) in deltas {
        out.push_str("\n# delta ");
        out.push_str(&policy_ref);
        out.push('\n');
        out.push_str(src.trim());
        out.push('\n');
    }
    Some(out)
}

fn print_control_response(response: serde_json::Value) -> Result<()> {
    if !response
        .get("ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        return Err(response
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("ActPlane control request failed")
            .to_string()
            .into());
    }
    if let Some(text) = response.get("text").and_then(|v| v.as_str()) {
        println!("{text}");
        return Ok(());
    }
    if let Some(result) = response.get("result") {
        println!("{}", serde_json::to_string_pretty(result)?);
        return Ok(());
    }
    println!("{}", serde_json::to_string_pretty(&response)?);
    Ok(())
}

async fn compile_policy(cli: &Cli, out: &Path) -> Result<i32> {
    let loaded = config::load_policy(cli)?;
    let resolved = config::resolve_policy(&loaded, cli.domain.as_deref())?;
    let compiled = dsl::compile_str(&resolved.source)?;
    std::fs::write(out, &compiled.bytes)?;
    if let Some(domain) = &resolved.domain {
        eprintln!(
            "ActPlane: domain `{}` (locked: {}; default: {})",
            domain.name,
            format_rule_list(&domain.locked),
            format_rule_list(&domain.defaults)
        );
    }
    eprintln!(
        "ActPlane: compiled {} rule(s) to {}",
        compiled.reasons.len(),
        out.display()
    );
    Ok(0)
}

fn format_rule_list(rules: &[String]) -> String {
    if rules.is_empty() {
        "none".into()
    } else {
        rules.join(", ")
    }
}
