# Release builds for macOS. The archives are made from a git commit, so commit first:
# uncommitted changes, including a fresh ui/dist/, are never included.
#
#   make tarball                 dist/wiretrace-<version>-macos.tar.gz + .sha256, from HEAD
#   make tarball COMMIT=v0.7.1   the same, from another commit or tag
#   make release                 the .tar.gz and the .dmg, each with a .sha256
#   make ui                      rebuild ui/dist/ (commit it before a release)
#   make icon                    rebuild app/Wiretrace.icns from app/icon.svg (needs rsvg-convert)
#   make install                 run the setup (./install), for developers: testers' Macs
#                                usually have no make, so the README uses ./install

COMMIT ?= HEAD
SETUP_ARGS ?=

.PHONY: help install tarball release ui icon clean

help:
	@echo "make install [SETUP_ARGS=…]   set up this folder, the same as ./install"
	@echo "make tarball [COMMIT=<ref>]   build dist/wiretrace-<version>-macos.tar.gz (+ .sha256)"
	@echo "make release [COMMIT=<ref>]   build the .tar.gz and the .dmg (+ .sha256 each)"
	@echo "make ui                       rebuild ui/dist/ with npm (commit it before a release)"
	@echo "make icon                     rebuild app/Wiretrace.icns from app/icon.svg (commit it)"
	@echo "make clean                    remove the release files of the current version from dist/"

install:
	./install $(SETUP_ARGS)

tarball:
	scripts/build-release.sh --tar-only $(COMMIT)

release:
	scripts/build-release.sh $(COMMIT)

ui:
	npm --prefix ui run build

icon:
	scripts/build-icon.sh

clean:
	@version=$$(sed -n 's/^__version__ = "\(.*\)"$$/\1/p' cli/__init__.py); \
	rm -fv dist/wiretrace-$$version-macos.tar.gz dist/wiretrace-$$version-macos.tar.gz.sha256 \
		dist/wiretrace-$$version-macos.dmg dist/wiretrace-$$version-macos.dmg.sha256
