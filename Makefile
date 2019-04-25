# Copyright (C) 2011-2013 Versile AS
#
# This file is part of Versile Python.
#
# Versile Python is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

RELEASE := $(shell python -c "import release ; print(release.release)")
HTML_NAME=versile-python-doc-html-$(RELEASE)
PDF_NAME=versile-python-doc-pdf-$(RELEASE)


help:
	@echo "Supported targets for \`make <target>\`"
	@echo
	@echo " dist        package all releases in preprocessed/ into dist/"
	@echo "             (dependencies not fully handled, make clean first)"
	@echo
	@echo " aprep       pre-process python v2 and v3 releases"
	@echo " aprep2      pre-process python v2 release"
	@echo " aprep3      pre-process python v3 release"
	@echo
	@echo " docdist     package doc for html/pdf/both doc in dist/"
	@echo " hdocdist    package doc for html doc in dist/"
	@echo " pdocdist    package doc for PDF doc in dist/"
	@echo
	@echo " doc         generate html and pdf documentation"
	@echo " html        generate html documentation"
	@echo " pdf         generate pdf documentation"
	@echo
	@echo " clean       perform full clean-up (including dist)"
	@echo " pyclean     clean up .pyc files"
	@echo " doc_clean   clean up documentation"
	@echo
	@echo " help        display this text"
	@echo
	@echo "Defined release is '$(RELEASE)' (edit 'release.py' to change)."
	@echo

dist: preprocessed/
	if [ ! -d dist/ ] ; then \
	  mkdir dist ; \
	fi
	( cd preprocessed/ ; \
	  for i in * ; \
	    do tar cvfz ../dist/$${i}.tgz $$i ; \
	  done )

aprep: aprep2 aprep3

aprep2: preprocessed_v2

aprep3: preprocessed_v3

preprocessed_v2: _release
	if [ ! -d preprocessed/ ] ; then mkdir preprocessed/ ; fi
	rm -rf preprocessed/versile-pythons-$(RELEASE)/
	./release.py 2 . preprocessed/

preprocessed_v3: _release
	if [ ! -d preprocessed/ ] ; then mkdir preprocessed/ ; fi
	rm -rf preprocessed/versile-python3-$(RELEASE)/
	./release.py 3 . preprocessed/
	if [ ! -d _tmp/ ] ; then mkdir _tmp/ ; fi
	2to3 preprocessed/versile-python3-$(RELEASE)/ > _tmp/2to3.patch
	patch -p0 < _tmp/2to3.patch

_release:
	@if [ ! -n "$(RELEASE)" ] ; then  echo "\nError: Need RELEASE\n" ; fi
	@test -n "$(RELEASE)"

doc: html pdf

html:
	(cd doc/ && make html)

latex:
	(cd doc/ && make latex)

pdf: latex
	(cd doc/_build/latex && make all-pdf)

docdist: hdocdist pdocdist

hdocdist: html
	rm -rf _dist/$(HTML_NAME)
	if [ ! -d _dist/ ] ; then mkdir _dist/ ; fi
	if [ ! -d _dist/$(HTML_NAME)/ ] ; then mkdir _dist/$(HTML_NAME)/; fi
	cp -r doc/_build/html/ _dist/$(HTML_NAME)/
	cp release/doc/files/* _dist/$(HTML_NAME)/
	if [ ! -d dist/ ] ; then mkdir dist ; fi
	(cd _dist ; tar cvfz ../dist/$(HTML_NAME).tgz $(HTML_NAME))
	rm -rf _dist/

pdocdist: pdf
	if [ ! -d dist/ ] ; then mkdir dist ; fi
	rm -f dist/$(PDF_NAME).pdf
	cp doc/_build/latex/VersilePython.pdf dist/$(PDF_NAME).pdf

clean: pyclean doc_clean
	rm -rf _dist/ dist/ preprocessed/ build/ _tmp/
	rm -f MANIFEST

pyclean:
	find . -name \*.pyc -exec rm \{\} \;

docclean: doc_clean

doc_clean:
	rm -f doc/conf.pyc
	(cd doc/ && make clean)
