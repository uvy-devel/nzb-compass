VERSION := $(shell python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
PROJECT := nzb-compass
ROOT := $(CURDIR)
ARCH_DIR := $(ROOT)/packaging/arch
OUTPUT_DIR := $(ROOT)/output
SOURCE_ARCHIVE := $(ARCH_DIR)/$(PROJECT)-$(VERSION).tar.gz

.PHONY: run test build validate-desktop check-version set-version package-arch prune-output clean-package

run:
	PYTHONPATH=src python3 -m nzb_compass

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

build:
	python3 -m build --wheel --no-isolation

validate-desktop:
	desktop-file-validate data/io.github.uvy-devel.NzbCompass.desktop

check-version:
	python3 packaging/check_version.py $(VERSION)

set-version:
	python3 packaging/set_version.py $(VERSION)

package-arch: test validate-desktop check-version
	mkdir -p $(OUTPUT_DIR)
	git archive --format=tar.gz --prefix=$(PROJECT)-$(VERSION)/ \
		-o $(SOURCE_ARCHIVE) HEAD
	cd $(ARCH_DIR) && PKGDEST=$(OUTPUT_DIR) makepkg -f --noconfirm
	$(MAKE) prune-output

prune-output:
	python3 packaging/prune_output.py $(OUTPUT_DIR)

clean-package:
	rm -rf $(ARCH_DIR)/src $(ARCH_DIR)/pkg
	rm -f $(SOURCE_ARCHIVE)
