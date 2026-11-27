"""Editor for World Tile's independent physical-material palette."""

from __future__ import annotations

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QPushButton, QVBoxLayout)

from ..material import MAX_PHYSICAL_MATERIALS, PHYSICAL_SURFACE_PROFILES, PhysicalMaterial, TerrainMaterial


class PhysicalMaterialDialog(QDialog):
    def __init__(self, material: TerrainMaterial, parent=None):
        super().__init__(parent)
        self.material = material
        self.setWindowTitle("Physical surface library")
        self.resize(520, 360)
        self._selected = -1
        self.changed = False

        self.items = QListWidget()
        self.name = QLineEdit()
        self.profile = QComboBox()
        self.profile.addItem("No profile", "")
        self.profile.addItem("Wood", PHYSICAL_SURFACE_PROFILES[0])
        self.profile.addItem("Metal", PHYSICAL_SURFACE_PROFILES[1])
        self.profile.addItem("Stone", PHYSICAL_SURFACE_PROFILES[2])
        self.profile.addItem("Ground", PHYSICAL_SURFACE_PROFILES[3])
        self.profile.addItem("Glass", PHYSICAL_SURFACE_PROFILES[4])
        self.friction = self._coefficient()
        self.restitution = self._coefficient()

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("ADM profile", self.profile)
        form.addRow("Friction (0..1)", self.friction)
        form.addRow("Restitution (0..1)", self.restitution)
        self.hint = QLabel("Physical assignments are separate from visual terrain surfaces.")
        self.hint.setWordWrap(True)

        self.add_button = QPushButton("Add new")
        self.save_button = QPushButton("Save")
        self.remove_button = QPushButton("Remove")
        self.done_button = QPushButton("Done")
        buttons = QHBoxLayout()
        for button in (self.add_button, self.save_button, self.remove_button, self.done_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.items, 1)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addLayout(buttons)

        self.items.currentRowChanged.connect(self._select)
        self.add_button.clicked.connect(self._new)
        self.save_button.clicked.connect(self._save)
        self.remove_button.clicked.connect(self._remove)
        self.done_button.clicked.connect(self.accept)
        self._refresh()

    @staticmethod
    def _coefficient() -> QLineEdit:
        edit = QLineEdit()
        validator = QDoubleValidator(0.0, 1.0, 6, edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        edit.setValidator(validator)
        return edit

    def _refresh(self) -> None:
        row = self.items.currentRow()
        self.items.blockSignals(True)
        self.items.clear()
        self.items.addItems([item.name for item in self.material.physical_materials])
        self.items.setCurrentRow(min(row, self.items.count() - 1))
        self.items.blockSignals(False)
        self._select(self.items.currentRow())

    def _select(self, row: int) -> None:
        self._selected = row
        if not 0 <= row < len(self.material.physical_materials):
            self.name.clear()
            self.profile.setCurrentIndex(0)
            self.friction.clear()
            self.restitution.clear()
            self.remove_button.setEnabled(False)
            return
        item = self.material.physical_materials[row]
        self.name.setText(item.name)
        self.profile.setCurrentIndex(max(0, self.profile.findData(item.profile)))
        self.friction.setText(str(item.friction))
        self.restitution.setText(str(item.restitution))
        self.remove_button.setEnabled(True)

    def _new(self) -> None:
        self.items.setCurrentRow(-1)
        self.name.clear()
        self.profile.setCurrentIndex(0)
        self.friction.clear()
        self.restitution.clear()
        self.name.setFocus()

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name or not self.friction.text() or not self.restitution.text():
            QMessageBox.warning(self, self.windowTitle(), "Enter a name, friction and restitution.")
            return
        old = None
        created = False
        try:
            if self._selected < 0 and len(self.material.physical_materials) >= MAX_PHYSICAL_MATERIALS:
                raise ValueError(f"At most {MAX_PHYSICAL_MATERIALS} physical materials are supported")
            if self._selected < 0:
                item = PhysicalMaterial(name, float(self.friction.text()), float(self.restitution.text()),
                                        self.profile.currentData())
                self.material.physical_materials.append(item)
                created = True
            else:
                old = self.material.physical_materials[self._selected]
                item = PhysicalMaterial(name, float(self.friction.text()), float(self.restitution.text()),
                                        self.profile.currentData(), old.id)
                self.material.physical_materials[self._selected] = item
            self.material.validate_physical_materials()
        except (ValueError, IndexError) as exc:
            if created:
                self.material.physical_materials.pop()
            elif old is not None:
                self.material.physical_materials[self._selected] = old
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.changed = True
        row = self._selected if self._selected >= 0 else len(self.material.physical_materials) - 1
        self._refresh()
        self.items.setCurrentRow(row)

    def _remove(self) -> None:
        if not 0 <= self._selected < len(self.material.physical_materials):
            return
        item = self.material.physical_materials[self._selected]
        if QMessageBox.question(self, self.windowTitle(),
                                f"Remove '{item.name}' and clear its painted assignments?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.material.remove_physical_material(self._selected)
        self.changed = True
        self._refresh()
