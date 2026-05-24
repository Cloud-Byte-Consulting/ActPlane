LATEXMK ?= latexmk
PDFLATEX ?= pdflatex

.PHONY: all abstract clean distclean

all: main.pdf

main.pdf: main.tex references.bib sections/*.tex acmart.cls ACM-Reference-Format.bst
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error main.tex

abstract: extended-abstract.pdf

extended-abstract.pdf: extended-abstract.tex acmart.cls
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error extended-abstract.tex

clean:
	$(LATEXMK) -c main.tex
	$(LATEXMK) -c extended-abstract.tex

distclean: clean
	rm -f main.pdf extended-abstract.pdf
