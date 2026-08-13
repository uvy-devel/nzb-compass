VERSION := 0.4.0
PROJECT := nzb-compass
ROOT := $(CURDIR)
ARCH_DIR := $(ROOT)/packaging/arch
OUTPUT_DIR := $(ROOT)/outputs
SOURCE_ARCHIVE := $(ARCH_DIR)/$(PROJECT)-$(VERSION).tar.gz

.PHONY: run test validate-desktop package-arch clean-package

run:
	PYTHONPATH=src python3 -m nzb_compass

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

validate-desktop:
	desktop-file-validate data/io.github.nzbcompass.NzbCompass.desktop

package-arch: test validate-desktop
	mkdir -p $(OUTPUT_DIR)
	tar --exclude='__pycache__' \
		--exclude='outputs' \
		--exclude='packaging/arch/src' \
		--exclude='packaging/arch/pkg' \
		--exclude='packaging/arch/*.pkg.tar.zst' \
		--transform='s,^,$(PROJECT)-$(VERSION)/,' \
		-czf $(SOURCE_ARCHIVE) \
		pyproject.toml README.md Makefile src tests data packaging/nzb-compass
	cd $(ARCH_DIR) && PKGDEST=$(OUTPUT_DIR) makepkg -f --noconfirm

clean-package:
	rm -rf $(ARCH_DIR)/src $(ARCH_DIR)/pkg
	rm -f $(SOURCE_ARCHIVE)

