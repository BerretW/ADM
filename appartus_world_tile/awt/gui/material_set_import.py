"""Review and safely import split material texture sets from a directory."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..material import TerrainMaterial
from ..material_set_import import (DEFAULT_SUFFIXES, MAP_NAMES, MaterialSet, MaterialSetScan,
                                   normalize_suffixes, resolve_material_set, scan_material_sets,
                                   validate_material_set_files)


class MaterialSetImportDialog(QDialog):
    """Preview discovered sets, let you choose conflicts, then validate selected textures."""

    def __init__(self, directory: str, material: TerrainMaterial, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import material sets from directory")
        self.setMinimumSize(780, 560)
        self._directory = directory
        self._existing_names = {surface.name.casefold() for surface in material.surfaces}
        self._settings = QSettings()
        self.scan: MaterialSetScan | None = None
        self.selected_names: set[str] = set()
        self.conflict_choices: dict[tuple[str, str], str] = {}
        self.update_existing = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "The importer searches subdirectories for explicitly named split maps. "
            "It never assigns packed _ma or unknown maps. Missing maps leave existing values unchanged.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.directory_label = QLabel(directory)
        self.directory_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.directory_label.setToolTip(directory)
        layout.addWidget(self.directory_label)

        suffix_group = QGroupBox("Configurable filename suffixes")
        suffix_layout = QGridLayout(suffix_group)
        self.suffix_fields: dict[str, QLineEdit] = {}
        saved = self._settings.value("material_set_import_suffixes", "")
        try:
            configured = json.loads(saved) if saved else DEFAULT_SUFFIXES
            configured = normalize_suffixes(configured)
        except (TypeError, ValueError, json.JSONDecodeError):
            configured = normalize_suffixes()
            QMessageBox.warning(self, "Texture suffixes",
                                "Saved suffix settings were invalid. The default suffixes are shown.")
        for index, map_name in enumerate(MAP_NAMES):
            column = (index // 4) * 2
            row = index % 4
            suffix_layout.addWidget(QLabel(map_name.title()), row, column)
            field = QLineEdit(", ".join(configured[map_name]))
            field.setToolTip("Comma-separated filename suffixes; a leading underscore is optional")
            suffix_layout.addWidget(field, row, column + 1)
            self.suffix_fields[map_name] = field
        self.rescan = QPushButton("Scan again")
        suffix_layout.addWidget(self.rescan, 3, 2, 1, 2)
        layout.addWidget(suffix_group)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Import", "Surface set", "Found maps", "Missing maps"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 250)
        layout.addWidget(self.table, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.update_existing_box = QCheckBox("Update matching existing surfaces")
        self.update_existing_box.setToolTip(
            "When enabled, replace only maps found in the selected set; missing maps keep their current values.")
        layout.addWidget(self.update_existing_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import selected")
        buttons.accepted.connect(self._accept_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.rescan.clicked.connect(self._scan_now)
        self._scan_now()

    def _suffixes(self) -> dict[str, str]:
        return {name: field.text() for name, field in self.suffix_fields.items()}

    def _scan_now(self) -> None:
        selected_before = {
            self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            for row in range(self.table.rowCount())
            if self.table.cellWidget(row, 0) and self.table.cellWidget(row, 0).isChecked()
        }
        try:
            self.scan = scan_material_sets(self._directory, self._suffixes())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Scan material sets", str(error))
            self.scan = None
            self.table.setRowCount(0)
            self.summary.setText("The directory could not be scanned.")
            return
        self.table.setRowCount(len(self.scan.sets))
        for row, item in enumerate(self.scan.sets):
            check = QCheckBox()
            check.setChecked(item.name in selected_before or
                             (not selected_before and item.name.casefold() not in self._existing_names))
            self.table.setCellWidget(row, 0, check)
            name_item = QTableWidgetItem(item.name)
            name_item.setData(Qt.ItemDataRole.UserRole, item.name)
            self.table.setItem(row, 1, name_item)
            found = []
            for map_name in MAP_NAMES:
                paths = item.files.get(map_name, ())
                if paths:
                    found.append(f"{map_name} ({len(paths)})")
            found_item = QTableWidgetItem(", ".join(found))
            candidates = [
                f"{map_name}: " + "; ".join(os.path.relpath(path, self.scan.root) for path in item.files[map_name])
                for map_name in item.conflicts
            ]
            found_item.setToolTip("\n".join(candidates))
            self.table.setItem(row, 2, found_item)
            missing = QTableWidgetItem(", ".join(item.missing_maps) or "None")
            self.table.setItem(row, 3, missing)
        self.summary.setText(
            f"Found {len(self.scan.sets)} sets. Ignored packed _ma maps: "
            f"{len(self.scan.ignored_packed_files)}; unknown files: {len(self.scan.unknown_files)}; "
            f"symbolic links skipped: {len(self.scan.skipped_links)}. Conflicts are shown in the Found maps tooltip.")
        details = self.scan.ignored_packed_files + self.scan.unknown_files + self.scan.skipped_links
        self.summary.setToolTip("\n".join(os.path.relpath(path, self.scan.root) for path in details))

    def _accept_import(self) -> None:
        if self.scan is None:
            QMessageBox.warning(self, "Import material sets", "Scan the directory before importing.")
            return
        selected = {
            self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            for row in range(self.table.rowCount())
            if self.table.cellWidget(row, 0).isChecked()
        }
        if not selected:
            QMessageBox.information(self, "Import material sets", "Select at least one material set.")
            return
        update_existing = self.update_existing_box.isChecked()
        choices: dict[tuple[str, str], str] = {}
        candidates = [item for item in self.scan.sets if item.name in selected]
        importable = [item for item in candidates
                      if update_existing or item.name.casefold() not in self._existing_names]
        if not importable:
            QMessageBox.information(
                self, "Import material sets",
                "All selected sets already exist. Enable updating existing surfaces to import their maps.")
            return
        try:
            for item in importable:
                for map_name in item.conflicts:
                    paths = item.files[map_name]
                    options = [os.path.relpath(path, self.scan.root) for path in paths]
                    chosen, accepted = QInputDialog.getItem(
                        self, f"Resolve {map_name} conflict", f"Choose the {map_name} map for {item.name}:",
                        options, 0, False)
                    if not accepted:
                        return
                    choices[(item.name, map_name)] = paths[options.index(chosen)]
                resolved = resolve_material_set(item, choices)
                validate_material_set_files(item, resolved)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Import material sets", str(error))
            return

        self._settings.setValue("material_set_import_suffixes", json.dumps(self._suffixes()))
        self.selected_names = selected
        self.conflict_choices = choices
        self.update_existing = update_existing
        super().accept()
