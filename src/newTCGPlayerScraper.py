from cProfile import label
import time
import math
import getopt
import re
import sys
import copy
import urllib.parse
from dotenv import load_dotenv
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.common.action_chains import ActionChains
import re
from collections import defaultdict
import itertools
from copy import deepcopy
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QToolBox, QGroupBox, QToolButton,
    QTextEdit, QPushButton, QLabel, QSizePolicy, QMessageBox, QStackedWidget, QFrame, QCheckBox,
    QSlider, QDialog, QSpacerItem
)
from PySide6.QtGui import QKeySequence, QIcon, QTransform, QTextOption
from PySide6.QtCore import Qt, Slot, QEvent, QObject, Signal, QThread, QPropertyAnimation, QSize, QRect
import sys

num_threads = 5
driver_pool = queue.Queue()

global_listings = []
global_listings_lock = threading.Lock()
global_stores = []
global_stores_lock = threading.Lock()

class InputWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.stack = QStackedWidget()
         # Add PAGE 0
        self.stack.addWidget(self.input_page())     # index 0
        self.stack.addWidget(self.results_page())   # index 1
        self.stack.addWidget(self.scrape_wait_page())# index 2
        self.stack.addWidget(self.beam_wait_page()) # index 3
        self.stack.addWidget(self.final_page())     # index 4

        # Add PAGE 1 (confirmation)
        #self.stack.addWidget(self.confirm_page())

        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        self.setWindowTitle("TCG Cart Optimizer")
        self.setMinimumSize(1600, 700)
        self.stack.setCurrentIndex(0)

    # --------------------------
    # PAGE 0 — Input Page
    # --------------------------
    def input_page(self):
        page = QWidget()   #page container
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Label
        lbl = QLabel("Paste your wanted-card lines below (one card per line).")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        # Large text edit
        self.text_edit = PlaceholderTextEdit()
        self.text_edit.setPlaceholderText(
            "Examples: \n"
            "  2 Sol Ring \n"
            "  1 Arcane Signet (Extended Art) [Foil] \n"
            "  1 Lightning Bolt [Non-Foil]\n"
            "  3 Counterspell (Original) \n"
        )
        #self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.text_edit, 1)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.submit_btn = QPushButton("Submit (Ctrl+Enter)")
        self.submit_btn.clicked.connect(self.on_submit)
        btn_row.addWidget(self.submit_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.on_clear)
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch()

        self.near_mint_chkbx = QCheckBox("Near Mint")
        self.near_mint_chkbx.setChecked(True)
        btn_row.addWidget(self.near_mint_chkbx)
        self.lightly_chkbx = QCheckBox("Lightly Played")
        self.lightly_chkbx.setChecked(True)
        btn_row.addWidget(self.lightly_chkbx)
        self.moderate_chkbx = QCheckBox("Moderately Played")
        self.moderate_chkbx.setChecked(True)
        btn_row.addWidget(self.moderate_chkbx)
        self.heavily_chkbx = QCheckBox("Heavily Played")
        btn_row.addWidget(self.heavily_chkbx)
        self.damaged_chkbx = QCheckBox("Damaged")
        btn_row.addWidget(self.damaged_chkbx)

        layout.addLayout(btn_row)

        # Status / preview area
        self.status_label = QLabel("Status: waiting for input")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Keyboard shortcut Ctrl+Enter
        submit_shortcut = QKeySequence(Qt.CTRL | Qt.Key_Return)
        self.submit_btn.setShortcut(submit_shortcut)

        # Support Enter key handling
        self.text_edit.installEventFilter(self)

        return page

    def eventFilter(self, obj, event):
        # Allow Ctrl+Enter from text edit to trigger submission
        if obj is self.text_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (event.modifiers() & Qt.ControlModifier):
                self.on_submit()
                return True
        return super().eventFilter(obj, event)

    @Slot()
    def on_submit(self):
        raw_text = self.text_edit.toPlainText()
        if not raw_text.strip():
            QMessageBox.warning(self, "Empty input", "Please paste or type some card lines first.")
            return

        try:
            parsed = load_desired_cards(raw_text)
        except Exception as e:
            self.status_label.setText(f"Error while parsing input: {e}")
            return

        # Construct the display string
        preview = ""
        for qty,name,printing,foil in parsed:
            if printing == "":
                printing = "Any Printing"
            if foil == "":
                foil = "Any Foil"
            card = str(qty) + "   " + name + "     " + printing + "    " + foil
            preview += card + "\n"

        preview += "\nAcceptable Conditions:\n"
        acceptable_conditions = []
        if self.near_mint_chkbx.isChecked():
            acceptable_conditions.append("Near+Mint")
            preview += "Near Mint  "
        if self.lightly_chkbx.isChecked():
            acceptable_conditions.append("Lightly+Played")
            preview += "Lightly Played  "
        if self.moderate_chkbx.isChecked():
            acceptable_conditions.append("Moderately+Played")
            preview += "Moderately Played  "
        if self.heavily_chkbx.isChecked():
            acceptable_conditions.append("Heavily+Played")
            preview += "Heavily Played  "
        if self.damaged_chkbx.isChecked():
            acceptable_conditions.append("Damaged")
            preview += "Damaged"

        # Show confirmation message box
        result = QMessageBox.question(
            self,
            "Confirm Cards",
            f"Please confirm the parsed cards:\n\n{preview}\n\nIs this correct?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result == QMessageBox.StandardButton.Yes:
            self.parsed = parsed

            self.acceptable_conditions = acceptable_conditions
            self.stack.setCurrentIndex(2)
            self.scrape_thread = QThread()
            self.scrape_worker = ScrapeWorker(parsed, acceptable_conditions)
            self.scrape_worker.moveToThread(self.scrape_thread)

            # Connect signals
            self.scrape_thread.started.connect(self.scrape_worker.run)
            self.scrape_worker.finished.connect(self.on_scrape_done)
            self.scrape_worker.error.connect(self.on_scrape_error)

            # Clean up after thread finishes
            self.scrape_worker.finished.connect(self.scrape_thread.quit)
            self.scrape_worker.finished.connect(self.scrape_worker.deleteLater)
            self.scrape_thread.finished.connect(self.scrape_thread.deleteLater)

            self.scrape_thread.start()

        else:
            # User clicked No — simply return to input screen
            return

    @Slot()
    def on_clear(self):
        self.text_edit.clear()
        self.status_label.setText("Status: cleared input")
    
    # --------------------------
    # PAGE 1 — results page
    # --------------------------
    def results_page(self):
        page = QWidget()

        outer = QVBoxLayout(page)

        # --- store the row so we can add columns later ---
        self.columns_row = QHBoxLayout()
        self.columns_row.setSpacing(5)
        self.columns_row.setAlignment(Qt.AlignTop)

        self.result_columns = []
        titles = ["Best Price", "Fewest Stores", "Balanced"]

        for title in titles:
            self._add_result_column(title)

        outer.addLayout(self.columns_row)

        # customize row
        customize_row = QHBoxLayout()
        customize_row.addStretch()
        customize_button = QPushButton("Build Custom Cart")
        customize_button.clicked.connect(lambda _, t="Custom": self.build_custom(t))
        customize_row.addWidget(customize_button)
        outer.addLayout(customize_row)

        return page

    def _add_result_column(self, title):
        col_widget = QFrame()
        col_widget.setFrameShape(QFrame.StyledPanel)
        col_layout = QVBoxLayout(col_widget)
        col_layout.setContentsMargins(2, 2, 2, 0)
        col_layout.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        col_layout.addWidget(lbl_title)

        info_box = QVBoxLayout()
        col_layout.addLayout(info_box)

        collapsible = CollapsibleSection("Show Items")
        col_layout.addWidget(collapsible)

        btn = QPushButton(f"Select {title} Cart")
        btn.clicked.connect(lambda _, t=title: self.add_to_cart(t))
        col_layout.addWidget(btn)

        self.result_columns.append({
            "title": title,
            "info": info_box,
            "items": collapsible,
            "widget": col_widget
        })

        self.columns_row.addWidget(col_widget, 1)

    def add_result_row(self, layout, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        layout.insertWidget(layout.count() - 1, lbl)  # before stretch

    def show_results(self, results):
        carts = ['best_price_cart','fewest_stores_cart','balanced_cart']

        for i in range(3):
            col = self.result_columns[i]

            # Always visible
            col["info"].addWidget(QLabel(f"Number of Stores: {results[carts[i]]['num_stores']}"))
            col["info"].addWidget(QLabel(f"Subtotal: ${results[carts[i]]['subtotal']:.2f}"))
            col["info"].addWidget(QLabel(f"Shipping (assuming $3 per package if not free shipping): ${results[carts[i]]['shipping']:.2f}"))
            col["info"].addWidget(QLabel(f"Total: ${results[carts[i]]['total_cost']:.2f}"))
            col["info"].addWidget(QLabel(f"Weights used:  coverage {str(results[carts[i]]['weights']['coverage'])}, variety {str(results[carts[i]]['weights']['variety'])}"))
            #col["info"].addWidget(QLabel(f"    coverage {str(results[carts[i]]['weights']['coverage'])}, variety {str(results[carts[i]]['weights']['variety'])}"))
            col["info"].addWidget(QLabel(f"    price_efficiency {str(results[carts[i]]['weights']['price_efficiency'])}, store_penalty {str(results[carts[i]]['weights']['store_penalty'])}"))

            # Collapsible items
            for store_id in results[carts[i]]['selected_store_ids']:
                label = QLabel(str(store_id))
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                col["items"].add_row(label)
                for listings in results[carts[i]]['cart'][store_id]['items'].items():
                    for listing_num in range(0, len(listings), 2): #the card name and price info are on different lines so skip every other line
                        card = "  " + listings[listing_num][0] #card name 
                        if listings[listing_num][1] != "": #printing
                            card += " " + listings[listing_num][1]
                        if listings[listing_num][2]: #foil
                            card += " " + listings[listing_num+1][0]["raw"]["foilness"]
                        else:
                            card += " Non-Foil"
                        label = QLabel(card)
                        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        col["items"].add_row(label)
                        for inner_listing in listings[listing_num+1]:
                            pricing = "    " + str(inner_listing["qty"]) + " x $" + str(inner_listing["price_each"]) + " = $" + str(inner_listing["total"]) + " | Market: $" + str(inner_listing["raw"]["market_price"]) + "  "  + str(inner_listing["raw"]["link"])
                            label = QLabel(pricing)
                            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                            col["items"].add_row(label)
        
    def add_to_cart(self, title):
        cart_key_map = {
            "Best Price": "best_price_cart",
            "Fewest Stores": "fewest_stores_cart",
            "Balanced": "balanced_cart",
            "Custom": "custom_cart"
        }

        key = cart_key_map.get(title)
        cart = self.cart_results.get(key)

        if not cart:
            QMessageBox.warning(self, "Missing Cart", "No cart results available.")
            return

        # Threading
        self.add_thread = QThread()
        self.add_worker = AddCartWorker(cart)
        self.add_worker.moveToThread(self.add_thread)

        self.add_thread.started.connect(self.add_worker.run)
        self.add_worker.finished.connect(self.add_thread.quit)
        self.add_worker.finished.connect(self.add_worker.deleteLater)
        self.add_thread.finished.connect(self.add_thread.deleteLater)

        self.add_worker.error.connect(lambda e: QMessageBox.warning(self, "Error", e))

        self.add_thread.start()

        self.stack.setCurrentIndex(4)

    # --------------------------
    # PAGE 2 — waiting page
    # --------------------------
    def scrape_wait_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(20, 20, 20, 20)

        # Stretch above and below centers the label
        layout.addStretch()

        lbl = QLabel("Currently scraping for your requested cards...")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(lbl)

        layout.addStretch()

        return page
    
    def on_scrape_done(self):
        #after scraping is finished
        self.stack.setCurrentIndex(3)
        self.beam_thread = QThread()
        self.beam_worker = BeamWorker(self.parsed)
        self.beam_worker.moveToThread(self.beam_thread)

        # Connect signals
        self.beam_thread.started.connect(self.beam_worker.run)
        self.beam_worker.finished.connect(self.on_beam_done)
        self.beam_worker.error.connect(self.on_beam_error)

        # Clean up after thread finishes
        self.beam_worker.finished.connect(self.beam_thread.quit)
        self.beam_worker.finished.connect(self.beam_worker.deleteLater)
        self.beam_thread.finished.connect(self.beam_thread.deleteLater)

        self.beam_thread.start()

    def on_scrape_error(self, error):
        print("dunno what happened here scrape error: " + error)
    
    def on_beam_error(self, error):
        print("dunno what happened here beam error: " + error)
        
    def on_beam_done(self, cart_results):
        #after store calculation is finished
        self.cart_results = cart_results
        self.stack.setCurrentIndex(1)
        self.show_results(self.cart_results)

    # --------------------------
    # PAGE 3 — waiting page 2
    # --------------------------
    def beam_wait_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(20, 20, 20, 20)

        # Stretch above and below centers the label
        layout.addStretch()

        lbl = QLabel("Currently optimizing carts...")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(lbl)

        layout.addStretch()

        return page
    
    # --------------------------
    # PAGE 4 — final page for adding carts
    # --------------------------
    def final_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(20, 20, 20, 20)

        # Stretch above and below centers the label
        layout.addStretch()

        lbl = QLabel("Adding the selected cart to your cart. Go to the last open browser and wait for it to finish. Leave this window open")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(lbl)

        layout.addStretch()

        return page

    def build_custom(self, title):
        dlg = WeightDialog(self)
        if dlg.exec() == QDialog.Accepted:
            weights = dlg.get_weights()
            self.custom_weights = weights

            # create a new beam worker with weights
            self.stack.setCurrentIndex(3)

            self.custom_thread = QThread()
            self.custom_worker = BeamWorker(self.parsed, weights=weights)
            self.custom_worker.moveToThread(self.custom_thread)

            self.custom_thread.started.connect(self.custom_worker.run)
            self.custom_worker.finished.connect(self.on_custom_beam_done)
            self.custom_worker.error.connect(self.on_beam_error)

            self.custom_worker.finished.connect(self.custom_thread.quit)
            self.custom_worker.finished.connect(self.custom_worker.deleteLater)
            self.custom_thread.finished.connect(self.custom_thread.deleteLater)

            self.custom_thread.start()
    
    def on_custom_beam_done(self, result):
        # append result to cart_results
        self.cart_results["custom_cart"] = result["balanced_cart"]

        # add the column dynamically
        self._add_result_column("Custom")

        # fill that column with data
        new_index = len(self.result_columns) - 1
        col = self.result_columns[new_index]

        # use same population logic
        cart = self.cart_results["custom_cart"]

        col["info"].addWidget(QLabel(f"Number of Stores: {result['balanced_cart']['num_stores']}"))
        col["info"].addWidget(QLabel(f"Subtotal: ${result['balanced_cart']['subtotal']:.2f}"))
        col["info"].addWidget(QLabel(f"Shipping (assuming $3 per package if not free shipping): ${result['balanced_cart']['shipping']:.2f}"))
        col["info"].addWidget(QLabel(f"Total: ${result['balanced_cart']['total_cost']:.2f}"))
        col["info"].addWidget(QLabel(f"Weights used:  coverage {str(result['balanced_cart']['weights']['coverage'])}, variety {str(result['balanced_cart']['weights']['variety'])}"))
        col["info"].addWidget(QLabel(f"    price_efficiency {str(result['balanced_cart']['weights']['price_efficiency'])}, store_penalty {str(result['balanced_cart']['weights']['store_penalty'])}"))

        for store_id in cart['selected_store_ids']:
            label = QLabel(str(store_id))
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col["items"].add_row(label)
            for listings in result["balanced_cart"]['cart'][store_id]['items'].items():
                for listing_num in range(0, len(listings), 2): #the card name and price info are on different lines so skip every other line
                    card = "  " + listings[listing_num][0] #card name 
                    if listings[listing_num][1] != "": #printing
                        card += " " + listings[listing_num][1]
                    if listings[listing_num][2]: #foil
                        card += " " + listings[listing_num+1][0]["raw"]["foilness"]
                    else:
                        card += " Non-Foil"
                    label = QLabel(card)
                    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    col["items"].add_row(label)
                    for inner_listing in listings[listing_num+1]:
                        pricing = "    " + str(inner_listing["qty"]) + " x $" + str(inner_listing["price_each"]) + " = $" + str(inner_listing["total"]) + " | Market: $" + str(inner_listing["raw"]["market_price"]) + "  "  + str(inner_listing["raw"]["link"])
                        label = QLabel(pricing)
                        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        col["items"].add_row(label)

        # update layout
        self.columns_row.update()
        self.stack.setCurrentIndex(1)


class ScrapeWorker(QObject):
    finished = Signal()     # send results back
    error = Signal(str)

    def __init__(self, cards, acceptable_conditions):
        super().__init__()
        self.cards = cards
        self.acceptable_conditions = acceptable_conditions

    @Slot()
    def run(self):
        try:
            # Call your long-running function
            start_scraping(self.cards,self.acceptable_conditions)
            shutdown_all_but_one_driver()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class BeamWorker(QObject):
    finished = Signal(object)     # send results back
    error = Signal(str)

    def __init__(self, cards, beam_width=10, weights=None):
        super().__init__()
        self.cards = cards
        self.beam_width = beam_width
        self.weights = weights

    @Slot()
    def run(self):
        try:
            # Call your long-running function
            results = process_stores(self.cards,self.beam_width,self.weights)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class CollapsibleSection(QWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)

        self.toggle_button = QToolButton(text=title, checkable=True, checked=False)
        self.toggle_button.setStyleSheet("QToolButton { font-weight: bold; }")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.clicked.connect(self.on_toggle)

        # This holds the actual rows
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(6, 2, 2, 2)
        self.content_layout.setSpacing(2)
        self.content_layout.setAlignment(Qt.AlignTop)

        # Scroll wrapper (optional)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.content)
        self.scroll.setMaximumHeight(0)  # start collapsed
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scroll.setAlignment(Qt.AlignTop)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.scroll)
        main_layout.setContentsMargins(0, 5, 0, 2)
        main_layout.setSpacing(5)
        main_layout.setAlignment(Qt.AlignTop)

    def on_toggle(self):
        if self.toggle_button.isChecked():
            self.toggle_button.setArrowType(Qt.DownArrow)
            self.scroll.setMaximumHeight(16777215)  # expand
            #self.scroll.setMinimumHeight(500)
        else:
            self.toggle_button.setArrowType(Qt.RightArrow)
            self.scroll.setMaximumHeight(0)  # collapse
            #self.scroll.setMinimumHeight(0)

    def add_row(self, widget):
        self.content_layout.addWidget(widget)

class AddCartWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, cart):
        super().__init__()
        self.cart = cart

    def run(self):
        try:
            driver = get_driver()
            add_potential_cart_to_cart(driver, self.cart)
            release_driver(driver)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class WeightDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Weights")
        self.resize(450, 300)

        layout = QVBoxLayout(self)

        self.sliders = {}
        names = ["coverage", "variety", "price_efficiency", "store_penalty"]
        descriptions = ["Picks stores with more coverage of wanted cards","Picks stores with more variety earlier","Values cheaper cards higher","Values less stores in the cart"]
        recommended_values = ["Recommended Values: 1-10","Recommended Values: 1-10","Recommended Values: 2-15","Recommended Values: 5-25"]

        for name,desc,rec in zip(names,descriptions,recommended_values):
            row = QHBoxLayout()

            label = QLabel(name)
            label.setMinimumWidth(90)
            row.addWidget(label)

            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(1)     # = 0.1
            slider.setMaximum(400)   # = 40.0
            slider.setValue(50)     # default = 10.0
            slider.setSingleStep(1)

            value_label = QLabel("5.0")
            value_label.setMinimumWidth(40)

            def make_callback(lbl):
                return lambda v: lbl.setText(f"{v/10:.1f}")

            slider.valueChanged.connect(make_callback(value_label))

            row.addWidget(slider)
            row.addWidget(value_label)

            layout.addLayout(row)
            desc_label = QLabel(desc)
            layout.addWidget(desc_label)
            rec_label = QLabel(rec)
            layout.addWidget(rec_label)
            layout.addSpacing(20)

            self.sliders[name] = slider

        button_row = QHBoxLayout()
        button_row.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        button_row.addWidget(ok_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def get_weights(self):
        return {name: [slider.value() / 10] for name, slider in self.sliders.items()}

class PlaceholderTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Overlay QLabel used as the multiline placeholder
        self._placeholder = QLabel(self)
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._placeholder.setStyleSheet("color: gray;")  # placeholder color
        self._placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # let clicks fall through to the edit
        self._placeholder.setMargin(4)

        # Keep placeholder on top visually
        self._placeholder.raise_()

        # Hide placeholder when the user types or there's content
        self.textChanged.connect(self._update_placeholder_visibility)

        # Initial visibility
        self._update_placeholder_visibility()

    def setPlaceholderText(self, text: str):
        """
        Accepts a multiline string. Use '\\n' for newlines.
        You can also embed HTML if you want formatting (then call setTextFormat on the label).
        """
        # If you prefer HTML formatting, do:
        # self._placeholder.setTextFormat(Qt.RichText)
        # self._placeholder.setText(html_text)
        self._placeholder.setText(text)
        self._update_placeholder_geometry()
        self._update_placeholder_visibility()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_placeholder_geometry()

    def _update_placeholder_geometry(self):
        # Place the placeholder inside the content area, leaving a small margin
        # We use viewport() geometry so the label sits where text starts in the text edit.
        try:
            vp = self.viewport().geometry()
            # Slight inset from left/top so cursor and text don't overlap.
            left_inset = 6
            top_inset = 6
            # width should account for vertical scrollbar if present
            width = vp.width() - left_inset - 6
            height = max(20, vp.height() - top_inset - 6)
            self._placeholder.setGeometry(QRect(vp.left() + left_inset, vp.top() + top_inset, width, height))
        except Exception:
            # fallback: full widget area
            self._placeholder.setGeometry(self.rect().adjusted(6, 6, -6, -6))

    def _update_placeholder_visibility(self):
        is_empty = (len(self.toPlainText().strip()) == 0)
        self._placeholder.setVisible(is_empty)

    # Optional convenience: let callers query/set placeholder via property
    def placeholderText(self):
        return self._placeholder.text()

def load_desired_cards(input):
    """Attempts to load the desired cards to search against store inventory from a txt file hat is space delimited. Format is: {qty} {name}. Reference example in desired_cards_example.txt.

    Args:
        file_location (string): file_location for wanted cards text file. 

    Returns:
        list: list of desired cards with quantity and name as fields.
    """
    desired_cards = []

    # format in file is {qty} {card name}
    cards = input.splitlines()
    for card in cards:
        card_parts = card.split(None, 1)
        card_parts.append(" ".join(p.strip() for p in re.findall(r"\((.*?)\)", card_parts[1])))
        card_parts.append(" ".join(p.strip() for p in re.findall(r"\[(.*?)\]", card_parts[1])))
        card_parts[1] = re.sub(r"\s*\(.*?\)\s*", "", card_parts[1]).strip()
        card_parts[1] = re.sub(r"\s*\[.*?\]\s*", "", card_parts[1]).strip()
        if card_parts[2]:
            if card_parts[2] == "Original":
                card_parts[2] = ""
            elif card_parts[2] == "":
                card_parts[2] = None
        if card_parts[3] and card_parts[3] == "":
            card_parts[3] = None

        desired_card = [card_parts[0], card_parts[1], card_parts[2], card_parts[3]]  # [qty, name, printing]
        desired_cards.append(desired_card)

    return desired_cards

def setup_selenium_driver(headless):
    """Sets up the Selenium driver based on a variety of settings.
    """
    options = ChromeOptions()

    # Does not like headless due to out of bounds, will need to look into this. Trying the headless=new flag for full featured Chrome, but new headless implementation
    # Headless=new requires Chrome 109. Need to add the Chrome installation dependency.
    if headless:
        options.add_argument("--headless=new")

    options.add_argument('--log-level=3')
    options.add_argument('--start-maximized')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    
    driver = Chrome(options=options)

    return driver

def init_driver_pool(headless):
    """Spin up the Chrome driver pool."""
    for _ in range(num_threads):
        driver_pool.put(setup_selenium_driver(headless))

def get_driver():
    """Get an available driver (blocks if none are free)."""
    return driver_pool.get()

def release_driver(driver):
    """Return a driver back to the pool."""
    driver_pool.put(driver)

def minimize_driver_pool():
    for driver in driver_pool():
        driver.minimize_window()
        time.sleep(2)

def maximize_driver_pool():
    for driver in driver_pool():
        driver.maximize_window()
        time.sleep(2)

def shutdown_driver_pool():
    """Close all Chrome instances at the end."""
    while not driver_pool.empty():
        driver = driver_pool.get()
        driver.quit()

def shutdown_all_but_one_driver():
    #keep one driver open for the final cart
    while driver_pool.qsize() > 1:
        driver = driver_pool.get()
        driver.quit()

def reset_tcgplayer_state(driver):
    # Load the domain so JS can access its local/session storage
    driver.get("https://www.tcgplayer.com")
    # small wait to ensure the app bootstraps
    time.sleep(0.5)

    # Clear local/session storage on that origin
    try:
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception as e:
        # If this fails, we'll fall back to other methods below
        print("execute_script clear failed:", e)

    # Delete cookies (clears cookies for all domains in the session)
    try:
        driver.delete_all_cookies()
    except Exception as e:
        print("delete_all_cookies failed:", e)

    # Navigate to a blank page
    driver.get("about:blank")
    time.sleep(1)

def search_card(card,acceptable_conditions=None,driver=None,num_retries=0):
    """searches for a card on the base tcgplayer page and returns a list of cards"""
    if driver is None:
        driver = get_driver()
    #shouldnt need to reset the state as new scraper doesnt use store pages
    #reset_tcgplayer_state(driver)
    
    def either_element_present(driver):
        results = driver.find_elements(By.CSS_SELECTOR, "div.search-result")
        blank = driver.find_elements(By.CSS_SELECTOR, "div.blank-slate")
        if results:
            return "results"
        elif blank:
            return "blank"
        else:
            if "tcgplayer.com/uhoh" in driver.current_url:
                return "uhoh"
            return False  # keep waiting
    
    #open the page
    url = "https://www.tcgplayer.com/search/magic/product?productLineName=Magic%3A+The+Gathering&q=" + urllib.parse.quote(card[1])
    if acceptable_conditions:
        url += "&Condition=" + "|".join(acceptable_conditions)

    driver.get(url)
    found = WebDriverWait(driver, 10).until(either_element_present)
    time.sleep(0.5)

    if found == "blank":
        return None
    if found == "uhoh":
        print("recursing because of uhoh page for url: " + url)
        if num_retries >= 10:
            print("too many retries, giving up on card: " + url)
            return None
        reset_tcgplayer_state(driver)
        time.sleep(120)
        uhoh_cards = search_card(card,acceptable_conditions,driver,num_retries=num_retries+1)
        if num_retries == 0:
            print("solved search_card uhoh problem")
            release_driver(driver)
        return uhoh_cards

    #get search results
    results = driver.find_elements(By.CSS_SELECTOR, "div.search-result")
    cards = []

    for result in results:
        try:
            og_name = result.find_element(By.CSS_SELECTOR, ".product-card__title").text
            name = re.sub(r"\s*\(.*?\)\s*", "", og_name).strip()
            if card[1].lower() != name.lower():
                continue
            printing = " ".join(p.strip() for p in re.findall(r"\((.*?)\)", og_name))
        except:
            continue
            name = "Unknown"
            printing = ""

        #only check the printing if we specified it
        #printings can be "Extended Art", "Borderless", "Galaxy Foil", "Anime", "Anime Borderless", "Showcase", "Textured Foil"
        if card[2] and card[2] != "" and card[2].strip().lower() != printing.lower():
            continue

        try:
            quantity = result.find_element(By.CSS_SELECTOR, ".inventory__listing-count").text
            quantity = "".join(char for char in quantity if char.isdigit())
        except:
            continue
            quantity = "N/A"

        try:
            link = result.find_element(By.TAG_NAME, "a").get_attribute("href")
        except:
            continue
            link = None

        try:
            market_price = result.find_element(By.CSS_SELECTOR, ".product-card__market-price--value").text
            market_price = market_price.replace("$","").replace(",","")
        except:
            #this should never happen but it happened once
            print("couldnt find market price for: " + link)
            continue
            market_price = "N/A"        
        
        try:
            mtg_set = result.find_element(By.CSS_SELECTOR, "div.product-card__set-name__variant").text
        except:
            mtg_set = "N/A"

        card_to_append = {
                "name": name,
                "link": link,
                "market_price": market_price,
                "quantity": quantity,
                "printing": printing,
                "set": mtg_set
            }
        cards.append(card_to_append)

    release_driver(driver)
    
    #make sure we dont include wildly overpriced cards
    cheapest_price = 99999.99
    cards_to_return = []
    for card in cards:
        if float(card["market_price"]) < cheapest_price:
            cheapest_price = float(card["market_price"])
    for card in cards:
        if cheapest_price < 1.0:
            if float(card["market_price"]) <= 1.0+cheapest_price:
                cards_to_return.append(card)  
        elif cheapest_price < 5.0:
            if float(card["market_price"]) <= 3.0+cheapest_price:
                cards_to_return.append(card) 
        else:
            if float(card["market_price"]) <= 5.0+cheapest_price:
                cards_to_return.append(card) 

    return cards_to_return

def get_total_pages(driver):
    try:
        # Find all the page number elements
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.tcg-pagination__pages a.tcg-button")))
        time.sleep(0.5)
        pages = driver.find_elements(By.CSS_SELECTOR, "div.tcg-pagination__pages a.tcg-button")

        page_numbers = []
        for el in pages:
            text = el.text.strip()
            if text.isdigit():
                page_numbers.append(int(text))

        if page_numbers:
            return max(page_numbers)
        else:
            return 1  # Only one page of results
    except Exception as e:
        print("Error getting page count:", e)
        return 1

def find_stores(card,driver=None,num_retries=0):
    """finds all the stores with free shipping over $5 for the given card"""

    if driver is None:
        driver = get_driver()

    def either_element_present(driver):
        results = driver.find_elements(By.CSS_SELECTOR, "div.tcg-input-select__trigger")
        blank = driver.find_elements(By.CSS_SELECTOR, "div.blank-slate")
        if results:
            return "results"
        elif blank:
            return "blank"
        else:
            if "tcgplayer.com/uhoh" in driver.current_url:
                return "uhoh"
            return False  # keep waiting

    #go to the card page
    driver.get(card["link"])
    try:
        result = WebDriverWait(driver, 20).until(either_element_present)
    except Exception as e:
        print(f"Error in find_stores timeout exception: {e}")
        result = "uhoh"
    time.sleep(0.5)

    if result == "blank":
        print("no results found for card: " + card["link"])
        exit()
        return
    if result == "uhoh":
        print("went to uhoh page for url: " + card["link"])
        if num_retries >= 10:
            print("too many retries, giving up on multiples card: " + card["link"])
            exit()
        reset_tcgplayer_state(driver)
        time.sleep(120)
        find_stores(card,driver,num_retries=num_retries+1)
        if num_retries == 0:
            print("solved find_stores uhoh problem")
            release_driver(driver)
        return

    triggers = driver.find_elements(By.CSS_SELECTOR, "div.tcg-input-select__trigger")
    triggers[1].click()
    
    time.sleep(0.5)  # tiny pause for dropdown animation
    
    # Find the desired item in the dropdown list
    items = driver.find_elements(By.CSS_SELECTOR, "ul.tcg-base-dropdown li.tcg-base-dropdown__item")
    for item in items:
        if item.text.strip() == str(50):
            item.click()
            break
    
    pages = get_total_pages(driver)
    #print("Total pages of results for card '" + card["name"] + "': " + str(pages))

    #paginate through all pages TODO: fix the thing where it goes instantly to the next page after the first one
    for page in range(1, pages + 1):
        if "page=" in card["link"]:
            # Replace existing page number
            paginated_url = re.sub(r"page=\d+", f"page={page}", card["link"])
        else:
            # Append page parameter
            separator = "&" if "?" in card["link"] else "?"
            paginated_url = f"{card['link']}{separator}page={page}"
        #paginated_url = card["link"] + "&page=" + str(page)
        #skip page 1 since we're already on it
        if page > 1:
            driver.get(paginated_url)
        
        result = None
        num_retries_pages = 0
        while result is None:
            try:
                result = WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section.listing-item")))
            except Exception as e:
                print(f"Error in find_stores pagination timeout exception: {e}")
                result = "uhoh"
            if result == "uhoh":
                print("went to uhoh page for url: " + card["link"])
                if num_retries_pages >= 10:
                    print("too many retries, giving up on multiples card: " + card["link"])
                    exit()
                reset_tcgplayer_state(driver)
                time.sleep(120)
                driver.get(paginated_url)
                result = None
                num_retries_pages += 1
        
        time.sleep(0.5)

        listings = driver.find_elements(By.CSS_SELECTOR, "section.listing-item")
        #find all stores with free shipping over $5
        for listing in listings:
            try:
                WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.listing-item__listing-data__info span")))
                listing_div = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info span")
            except:
                #why are we here?
                print("no listing div??")
                listing_div = None

            # Check for free shipping link
            has_free_shipping_link = False
            # Case 1: Free shipping over $5
            if listing_div:
                try:
                    # Case 1: Free shipping over $5
                    free_link = listing_div.find_element(By.CSS_SELECTOR, "a.free-shipping-over-min")
                    if "Over $5" in free_link.text and not "Over $50" in free_link.text:
                        has_free_shipping_link = True
                except:
                    # Case 2: Shipping included
                    try:
                        shipping_links = listing.find_elements(By.TAG_NAME, "a")

                        for link in shipping_links:
                            link_text = link.text.strip()
                            href = link.get_attribute("href") or ""

                            if "Included" in link_text or "Shipping-Included" in href:
                                has_free_shipping_link = True
                                break
                    except:
                        pass

            # Only keep if qualifies
            if has_free_shipping_link:
                try:
                    seller_name = listing.find_element(By.CSS_SELECTOR, "a.seller-info__name").text.strip()
                    seller_id = listing.find_element(By.CSS_SELECTOR, "a.seller-info__name").get_attribute("href").split("/")[-1]
                except Exception as e:
                    print(f"Error processing store: {e}")
                    continue

                try:
                    price = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info__price").text.strip()
                    price = price.replace("$","").replace(",","")
                except Exception as e:
                    print(f"Error processing store: {e}")
                    continue

                try:
                    rating = listing.find_element(By.CSS_SELECTOR, "div.seller-info__rating").text.strip()
                except Exception as e:
                    print(f"Error processing store: {e}")
                    rating = "N/A"

                try:
                    sales = listing.find_element(By.CSS_SELECTOR, "div.seller-info__sales").text.strip()
                except Exception as e:
                    print(f"Error processing store: {e}")
                    sales = "N/A"
                
                try:
                    quantity = listing.find_element(By.CSS_SELECTOR, "span.add-to-cart__available").text.strip()
                    quantity = "".join(char for char in quantity if char.isdigit())
                except Exception as e:
                    print(f"Error processing store: {e}")
                    continue

                try:
                    quality = listing.find_element(By.CSS_SELECTOR, "h3.listing-item__listing-data__info__condition").text.strip()
                    foil = "Foil" if "Foil" in quality else "Non-Foil"
                except:
                    quality = ""

                try:
                    link = paginated_url
                except:
                    continue
                    link = ""

                with global_listings_lock:
                    global_listings.append({
                        "card": card,
                        "seller_name": seller_name,
                        "seller_id": seller_id,
                        "price": price,
                        "rating": rating,
                        "sales": sales,
                        "quantity": quantity,
                        "quality": quality,
                        "link": link,
                        "foilness": foil
                    })
    
    release_driver(driver)
    return

def coagulate_stores_by_listings():
    """Coagulates global listings into stores with cards scanned."""
    with global_listings_lock:
        for listing in global_listings:
            # Check if store already exists
            store_found = False
            with global_stores_lock:
                for store in global_stores:
                    if store["seller_id"] == listing["seller_id"]:
                        #make sure we dont get duplicates in the case where user wants to specify more than one printing
                        add = True
                        for card_listing in store["cards_scanned"]:
                            if card_listing["name"] == listing["card"]["name"] and card_listing["printing"] == listing["card"]["printing"] and card_listing["quality"] == listing["quality"]:
                                #this is the exact same card, dont add it
                                add = False
                                break
                        if add:
                            # Add card to existing store
                            store["cards_scanned"].append({
                                "name": listing["card"]["name"],
                                "price": listing["price"],
                                "market_price": listing["card"]["market_price"],
                                "quantity": listing["quantity"],
                                "link": listing["link"],
                                "printing": listing["card"]["printing"],
                                "set": listing["card"]["set"],
                                "quality": listing["quality"],
                                "foilness": listing["foilness"]
                            })
                            store_found = True
                            break

                if not store_found:
                    # Create new store entry
                    new_store = {
                        "seller_name": listing["seller_name"],
                        "seller_id": listing["seller_id"],
                        "rating": listing["rating"],
                        "sales": listing["sales"],
                        "cards_scanned": [{
                            "name": listing["card"]["name"],
                            "price": listing["price"],
                            "market_price": listing["card"]["market_price"],
                            "quantity": listing["quantity"],
                            "link": listing["link"],
                            "printing": listing["card"]["printing"],
                            "set": listing["card"]["set"],
                            "quality": listing["quality"],
                            "foilness": listing["foilness"]
                        }]
                    }
                    global_stores.append(new_store)

    return 
    
def estimate_beam_runtime(wanted_cards, stores, beam_width, num_weight_configs=1):
    """
    Rough estimate of beam search runtime in seconds
    based on problem size and user-configured beam width.
    """
    num_cards = len(wanted_cards)
    num_stores = len(stores)

    # Rough estimate: beam_width * depth * avg_branching
    depth = min(num_cards, num_stores)  # max depth ≈ number of cards to cover
    avg_branching = num_stores / max(1, num_cards)  # avg stores per card

    estimated_ops = beam_width * num_cards * num_stores * num_stores * num_weight_configs
    estimated_seconds = estimated_ops * 0.000000017 #how many seconds per operation

    return estimated_seconds

def generate_multiple_carts(
    wanted_cards, stores, weights=None,
    beam_width=10, time_limit=60, top_k_per_wanted=40, debug=False
):
    """
    Beam search cart builder that:
      - preserves printing/foil semantics (None => any, "" => original)
      - respects per-listing quantities
      - uses weights dict to score states:
          weights = {
            'coverage': float,
            'variety': float,
            'price_efficiency': float,
            'store_penalty': float
          }
      - prioritizes reuse of already-selected stores when expanding
    Returns: dict with best_price_cart, fewest_stores_cart, balanced_cart, all_results
    """
    import time
    from copy import deepcopy

    start_time = time.time()
    if weights is None:
        weights = {'coverage': 5.0, 'variety': 2.0, 'price_efficiency': 1.0, 'store_penalty': 1.0}

    # -------------------------
    # Normalizers / parsers
    # -------------------------
    def _norm_name(x):
        return "" if x is None else str(x).strip().lower()

    def _norm_printing_wanted(x):
        if x is None:
            return None
        s = str(x).strip()
        return "" if s == "" else s.lower()

    def _norm_printing_listing(x):
        if x is None:
            return ""
        s = str(x).strip()
        return "" if s == "" else s.lower()

    def _norm_foil(x):
        if x is None:
            return None
        if isinstance(x, bool):
            return "foil" if x else "nonfoil"
        s = str(x).strip().lower()
        if s in ("foil", "f"):
            return "foil"
        if s in ("nonfoil", "non-foil", "non", "n", "non foil"):
            return "nonfoil"
        return None

    def _parse_qty(lst):
        q = lst.get("quantity", 0)
        try:
            return int(q)
        except:
            try:
                return int(str(q).strip().split()[0])
            except:
                return 0

    def _parse_price(lst):
        p = lst.get("price", None)
        try:
            return float(p)
        except:
            try:
                s = str(p)
                return float(s.replace("$", "").replace(",", ""))
            except:
                return float("inf")

    def _parse_market(lst):
        m = lst.get("market_price", None)
        try:
            return float(m)
        except:
            try:
                s = str(m)
                return float(s.replace("$", "").replace(",", ""))
            except:
                return 0.0

    # -------------------------
    # Build wanted_keys and needed_list
    # -------------------------
    wanted_keys = []
    needed_map = {}
    for entry in wanted_cards:
        if len(entry) == 4:
            qty, name, printing, foil = entry
        elif len(entry) == 3:
            qty, name, printing = entry
            foil = None
        else:
            raise ValueError("wanted_cards entries must be length 3 or 4")

        key = (_norm_name(name), _norm_printing_wanted(printing), _norm_foil(foil))
        if key not in needed_map:
            wanted_keys.append(key)
            needed_map[key] = 0
        needed_map[key] += int(qty)

    needed_list = [needed_map[k] for k in wanted_keys]
    W = len(wanted_keys)
    if debug:
        print("WANTED KEYS:", wanted_keys)
        print("NEEDED LIST:", needed_list)

    # -------------------------
    # Build listing_index per store (normalized) and initial_avail map
    # -------------------------
    listing_index = {}   # sid -> list of listings (normalized)
    initial_avail = {}   # (sid, idx) -> qty
    # Also store market price for price_eff calc
    for s in stores:
        sid = s["seller_id"]
        out = []
        for lst in s.get("cards_scanned", []):
            name_l = _norm_name(lst.get("name"))
            printing_l = _norm_printing_listing(lst.get("printing"))
            # common foil keys
            raw_foil = None
            for k in ("foil", "is_foil", "foilness", "isfoil"):
                if k in lst:
                    raw_foil = lst.get(k)
                    break
            foil_l = _norm_foil(raw_foil)
            price = _parse_price(lst)
            qty = _parse_qty(lst)
            market = _parse_market(lst)
            out.append({
                "name": name_l,
                "printing": printing_l,
                "foil": foil_l,
                "price": price,
                "qty": qty,
                "market": market,
                "raw": lst
            })
        listing_index[sid] = out
        for idx, L in enumerate(out):
            initial_avail[(sid, idx)] = int(L["qty"])

    # -------------------------
    # Matching predicate for a wanted key and listing
    # wanted key: (name, printing_wanted, foil_wanted)
    # printing_wanted: None => any, "" => original only, string => exact
    # foil_wanted: None => any, "foil"/"nonfoil" => exact
    # -------------------------
    def _matches(wk, L):
        wn, wp, wf = wk
        if L["name"] != wn:
            return False

        lp = L["printing"]
        if wp is not None:
            if wp == "":
                if lp != "":
                    return False
            elif lp != wp:
                return False

        lf = L["foil"]
        if wf is not None:
            if wf == "nonfoil":
                if lf not in (None, "", "nonfoil"):
                    return False
            else:
                if lf != wf:
                    return False

        return True

    # -------------------------
    # Build match_sets for each wanted index (list of (sid, idx, price))
    # Trim to top_k_per_wanted cheapest.
    # -------------------------
    match_sets = [[] for _ in range(W)]
    for sid, lsts in listing_index.items():
        for idx, L in enumerate(lsts):
            for wi, wk in enumerate(wanted_keys):
                if wk[0] != L["name"]:
                    continue
                if _matches(wk, L):
                    match_sets[wi].append((sid, idx, L["price"]))

    for wi in range(W):
        match_sets[wi].sort(key=lambda x: x[2])
        if top_k_per_wanted and len(match_sets[wi]) > top_k_per_wanted:
            match_sets[wi] = match_sets[wi][:top_k_per_wanted]

    if debug:
        empties = [wanted_keys[i] for i in range(W) if not match_sets[i]]
        if empties:
            print("No candidates for:", empties)

    # -------------------------
    # Helper: compute current avail from used_map
    # used_map: dict (sid, idx) -> {wi: qty}
    # -------------------------
    def current_avail(sid, idx, used_map):
        k = (sid, idx)
        used_total = 0
        inner = used_map.get(k)
        if inner:
            for v in inner.values():
                used_total += v
        return max(0, initial_avail.get(k, 0) - used_total)

    # -------------------------
    # Beam state: (selected_stores_tuple, remaining_tuple, used_map)
    # used_map: (sid, idx) -> dict {wi: qty}
    # -------------------------
    beam = [(tuple(), tuple(needed_list), {})]
    finished = []

    # -------------------------
    # Main loop
    # -------------------------
    layer = 0
    while beam and (time.time() - start_time) < time_limit:
        layer += 1
        new_states = []

        for sel, rem, used in beam:
            # complete?
            if all(r <= 0 for r in rem):
                finished.append((sel, rem, used))
                continue

            # candidate wanted indices with remaining >0 and candidates exist
            cand_wi = [i for i in range(W) if rem[i] > 0 and match_sets[i]]
            if not cand_wi:
                continue

            # pick key to expand (largest remaining)
            wi = max(cand_wi, key=lambda i: rem[i])
            need_qty = rem[wi]
            wk = wanted_keys[wi]
            is_any_key = (wk[1] is None and wk[2] is None)

            # prefer listings from stores already in sel
            sel_set = set(sel)
            candidates = match_sets[wi]
            in_sel = [c for c in candidates if c[0] in sel_set]
            out_sel = [c for c in candidates if c[0] not in sel_set]
            ordered = in_sel + out_sel

            for sid, idx, price in ordered:
                avail_qty = current_avail(sid, idx, used)
                if avail_qty <= 0:
                    continue

                # ANY guard: if listing already partially used by other wanted keys,
                # ensure remaining is enough to satisfy at least 1 for this ANY key
                if is_any_key:
                    k = (sid, idx)
                    if k in used:
                        other_wis = [x for x in used[k].keys() if x != wi]
                        if other_wis and avail_qty <= 0:
                            continue

                take = min(avail_qty, need_qty)
                if take <= 0:
                    continue

                # create new state (shallow copies of small structures)
                new_sel = tuple(sorted(set(sel) | {sid}))
                new_rem = list(rem)
                new_rem[wi] = max(0, new_rem[wi] - take)
                new_rem = tuple(new_rem)

                new_used = used.copy()
                k = (sid, idx)
                inner = new_used.get(k)
                if inner is None:
                    new_used[k] = {wi: take}
                else:
                    new_inner = inner.copy()
                    new_inner[wi] = new_inner.get(wi, 0) + take
                    new_used[k] = new_inner

                new_states.append((new_sel, new_rem, new_used))

        if not new_states:
            break

        # -------------------------
        # Scoring function using weights
        # -------------------------
        def score_state(state):
            sel, rem, used_map = state
            # coverage / variety
            covered_units = sum(needed_list[i] - rem[i] for i in range(W))
            covered_unique = sum(1 for i in range(W) if rem[i] < needed_list[i])

            # estimate price and price_eff
            store_subtotals = {}
            price_eff_sum = 0.0
            price_eff_count = 0
            for (sid, idx), inner in used_map.items():
                L = listing_index[sid][idx]
                p = L["price"]
                m = L.get("market", 0.0)
                qty = sum(inner.values())
                store_subtotals[sid] = store_subtotals.get(sid, 0.0) + p * qty
                # price eff accumulation: use market/price where possible
                if p > 0:
                    price_eff_sum += (m / p)
                    price_eff_count += qty

            price_eff = (price_eff_sum / price_eff_count) if price_eff_count else 0.0

            # shipping estimation
            SHIPPING = 3.0
            FREE = 5.0
            estimated_shipping = sum(SHIPPING for s_id, sub in store_subtotals.items() if sub < FREE)

            total_est_price = sum(store_subtotals.values()) + estimated_shipping
            store_ct = len(store_subtotals)

            # Score: combine weights properly
            # higher is better -> reward coverage/variety/price_eff, penalize store count and price
            price_penalty_coeff = 1.0  # scales how strongly price matters in score
            score = (weights["coverage"] * covered_units +
                     weights["variety"] * covered_unique +
                     weights["price_efficiency"] * price_eff -
                     weights["store_penalty"] * store_ct -
                     price_penalty_coeff * total_est_price)

            # small tiebreakers: prefer fewer stores, then lower price
            return score

        # prune & keep top beam_width
        new_states.sort(key=score_state, reverse=True)
        beam = new_states[:beam_width]

        if debug and layer % 5 == 0:
            # simple debug snapshot
            top = beam[0] if beam else None
            if top:
                sel_t, rem_t, used_t = top
                if debug:
                    print(f"[debug] layer {layer} top sel {sel_t} covered {sum(needed_list[i]-rem_t[i] for i in range(W))}")

    # states to convert: finished (complete) else beam partials
    results_states = finished if finished else beam

    # -------------------------
    # Build final results from used_map
    # -------------------------
    final_results = []
    for sel, rem, used in results_states:
        cart = {}
        for sid in sel:
            cart[sid] = {"items": {}, "subtotal": 0.0, "shipping": 0.0, "total": 0.0}

        for (sid, idx), inner in used.items():
            L = listing_index[sid][idx]
            for wi, qty in inner.items():
                if qty <= 0:
                    continue
                wk = wanted_keys[wi]
                cart.setdefault(sid, {"items": {}, "subtotal": 0.0, "shipping": 0.0, "total": 0.0})
                cart[sid]["items"].setdefault(wk, []).append({
                    "qty": int(qty),
                    "price_each": L["price"],
                    "total": qty * L["price"],
                    "raw": L["raw"]
                })
                cart[sid]["subtotal"] += qty * L["price"]

        for sid, st in cart.items():
            st["shipping"] = 0.0 if st["subtotal"] >= 5.0 else 3.0
            st["total"] = st["subtotal"] + st["shipping"]
        
        subtotal = sum(st["subtotal"] for st in cart.values())
        shipping = sum(st["shipping"] for st in cart.values())
        total_cost = sum(st["total"] for st in cart.values())
        final_results.append({
            "selected_store_ids": list(sel),
            "cart": cart,
            "subtotal": subtotal,
            "shipping": shipping,
            "total_cost": total_cost,
            "num_stores": len(cart),
            "weights": weights
        })

    # sort and pick bests
    final_results.sort(key=lambda r: (r["total_cost"], r["num_stores"]))
    if not final_results:
        return {"best_price_cart": None, "fewest_stores_cart": None, "balanced_cart": None, "all_results": []}

    best_price_cart = min(final_results, key=lambda r: r["total_cost"])
    fewest_stores_cart = min(final_results, key=lambda r: r["num_stores"])
    # balanced uses weights.store_penalty to combine
    balanced_cart = min(final_results, key=lambda r: r["total_cost"] + weights["store_penalty"] * r["num_stores"])

    return {
        "best_price_cart": best_price_cart,
        "fewest_stores_cart": fewest_stores_cart,
        "balanced_cart": balanced_cart,
        "all_results": final_results
    }

def print_cart(result):
    """
    Pretty-prints a cart produced by generate_multiple_carts().
    Supports:
        - multiple listings per wanted card key
        - printing=None / "" / value
        - foil=None / foil / nonfoil
    """
    if not result or not result.get("cart"):
        print("No cart to display.")
        return

    cart = result["cart"]
    overall_total = 0.0

    def fmt_printing(p):
        if p is None: return ""
        if p == "": return ""
        return p.capitalize()

    def fmt_foil(f):
        if f is None: return "Non-Foil"
        if f == "foil": return "Foil"
        if f == "nonfoil": return "Non-Foil"
        return f

    print("========== CART DETAILS ==========\n")
    print(f"Weights: {result["weights"]}")

    for sid, store_data in cart.items():
        print(f"--- Store: {sid} ---")
        items = store_data.get("items", {})

        if not items:
            print("  (No items)")
            continue

        for wk, listings in items.items():
            name, printing, foil = wk
            printing_str = fmt_printing(printing)
            foil_str = fmt_foil(foil)
            
            print(f"  {name}  | {printing_str} {foil_str}")

            for lst in listings:
                qty = lst.get("qty", 0)
                price_each = lst.get("price_each", 0.0)
                total = lst.get("total", 0.0)
                market = float(lst["raw"]["market_price"])

                print(f"    - {qty} × ${price_each:.2f}  =  ${total:.2f} | Market: ${market:.2f}")

        subtotal = store_data.get("subtotal", 0.0)
        shipping = store_data.get("shipping", 0.0)
        total = store_data.get("total", subtotal + shipping)

        overall_total += total

        print(f"  Subtotal: ${subtotal:.2f}")
        print(f"  Shipping: ${shipping:.2f}")
        print(f"  Total for store: ${total:.2f}")
        print()

    print("===================================")
    print(f"Grand Total Across Stores: ${overall_total:.2f}")
    print("===================================\n")
     
def add_potential_cart_to_cart(driver,cart):

    def either_element_present(driver):
        try:
            driver.find_element(By.CSS_SELECTOR, "section.listing-item")
            return "results"
        except:
            pass
        try:
            driver.find_element(By.CSS_SELECTOR, "div.blank-slate")
            return "blank"
        except:
            pass
        if "tcgplayer.com/uhoh" in driver.current_url:
            return "uhoh"
        return False  # keep waiting

    for storeid in cart["selected_store_ids"]:
        for item in cart["cart"][storeid]["items"]:
            for listing in cart["cart"][storeid]["items"][item]:
                link = listing["raw"]["link"]
                driver.get(link)
                result = WebDriverWait(driver, 20).until(either_element_present)
                time.sleep(0.5)

                if result == "blank":
                    print("no results found for card: " + link)
                    exit()
                    return
                if result == "uhoh":
                    print("went to uhoh page for url: " + link)
                    reset_tcgplayer_state(driver)
                    time.sleep(120)
                    driver.get(link)
                    result = WebDriverWait(driver, 20).until(either_element_present)
                    time.sleep(0.5)
                if result == "blank":
                    print("no results found for card: " + link)
                    exit()
                    return
                
                qty_to_add = str(listing["qty"])
                #try to add it to the cart
                listings = driver.find_elements(By.CSS_SELECTOR, "section.listing-item")
                
                for driver_listing in listings:
                    try:
                        WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.listing-item__listing-data__info span")))
                        listing_div = driver_listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info span")
                    except:
                        #why are we here?
                        print("no listing div??")
                        listing_div = None

                    if listing_div:
                        try:
                            seller_id = driver_listing.find_element(By.CSS_SELECTOR, "a.seller-info__name").get_attribute("href").split("/")[-1]
                        except Exception as e:
                            print(f"Error processing store: {e}")
                            continue

                        if seller_id == storeid:
                            #this is our store, make sure it is the same printing, as each store can have multiple listings by quality
                            try:
                                quality = driver_listing.find_element(By.CSS_SELECTOR, "h3.listing-item__listing-data__info__condition").text.strip()
                                if quality != listing["raw"]["quality"]:
                                    continue

                                if int(qty_to_add) > 1:
                                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", driver_listing)
                                    time.sleep(0.5)
                                    target = driver_listing.find_element(By.CSS_SELECTOR, "div.add-to-cart__dropdown__overlay")
                                    ActionChains(driver).move_to_element(target).pause(0.05).click(target).perform()
                                    time.sleep(0.5)

                                qty_dropdown = driver_listing.find_element(By.CSS_SELECTOR, "select[data-testid='mp-select__UpdateProductQuantity']")
                                select = Select(qty_dropdown)
                                available_values = [opt.get_attribute("value") for opt in select.options]
                                #choose how many
                                select.select_by_value(qty_to_add)
                                button = driver_listing.find_element(By.CSS_SELECTOR, "button[data-testid^='add-to-cart__submit--']")
                                #click button
                                driver.execute_script("arguments[0].click();", button)
                                time.sleep(3)
                                break
                            except Exception as e:
                                print(f"Error adding card from {link}: {e}")
                                print("Card details: ")
                                print(listing)
                                print("available values: " + str(available_values))
    return

def search_multiple_weight_configs(wanted_cards, stores, weight_grid, beam_width, time_limit):
    """
    weight_grid: dict where each key has a LIST of possible values, e.g.:
    {
        "price": [1.0, 2.0],
        "packages": [0.5, 1.0, 2.0],
        "market_diff": [0.1, 0.2]
    }
    """

    # 1) Expand to all combinations
    keys = list(weight_grid.keys())
    value_lists = [weight_grid[k] for k in keys]

    weight_sets = []
    for combo in itertools.product(*value_lists):
        weight_sets.append(dict(zip(keys, combo)))

    results = []

    # 2) Run NEW cart-building algorithm on each weight set
    for weight_config in weight_sets:
        result = generate_multiple_carts(
            wanted_cards=wanted_cards,
            stores=stores,
            weights=weight_config,
            beam_width=beam_width,
            time_limit=time_limit
        )

        if result is not None:
            results.append({
                "weights": weight_config,
                "result": result
            })

    

    # 3) Pick the best cart from ALL weight searches
    best_price_cart = min(results, key=lambda r: r["result"]["best_price_cart"]["total_cost"])
    fewest_stores_cart = min(results, key=lambda r: r["result"]["fewest_stores_cart"]["num_stores"])
    balanced_cart = min(results, key=lambda r: r["result"]["balanced_cart"]["total_cost"] + r["weights"]["store_penalty"]*r["result"]["balanced_cart"]["num_stores"])

    return {
        "results_per_weight": results,
        "best_price_cart": best_price_cart["result"]["best_price_cart"],
        "fewest_stores_cart": fewest_stores_cart["result"]["fewest_stores_cart"],
        "balanced_cart": balanced_cart["result"]["balanced_cart"]
    }

def start_scraping(desired_cards,acceptable_condidtions):
        
    start = time.time()

    num_desired_cards = 0
    for desired_card in desired_cards:
        num_desired_cards += int(desired_card[0])

    print("Total desired cards to search for: " + str(num_desired_cards))
        
    #start the scraping
    init_driver_pool(False)

    #start of initial card scanning on fresh pages
    cards_to_check = []
    cards_to_check_lock = threading.Lock()

    MAX_THREADS = min(num_desired_cards, num_threads)

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [executor.submit(search_card, desired_card, acceptable_condidtions) for desired_card in desired_cards]

        for future in as_completed(futures):
            try:
                cards = future.result()  # will raise if there was an exception
                if cards:
                    for card in cards:
                        with cards_to_check_lock:
                            cards_to_check.append(card)
            except Exception as e:
                print(f"Error in search_card thread: {e}")

    #if user wanted multiple cards of the same name but specified different printings, make sure we dont scrape same card twice to save time
    new_cards_to_check = []
    for card in cards_to_check:
        if card not in new_cards_to_check:
            new_cards_to_check.append(card)
    
    MAX_THREADS = min(len(new_cards_to_check), num_threads)

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [executor.submit(find_stores, card) for card in new_cards_to_check]

        for future in as_completed(futures):
            try:
                future.result()  # will raise if there was an exception
            except Exception as e:
                print(f"Error in find_stores thread: {e}")

    scrape = time.time()
    print("Scraping took " + str(scrape - start) + " seconds")

def process_stores(desired_cards,beam_width=10,weights=None):

    scrape = time.time()

    coagulate_stores_by_listings()

    stores = copy.deepcopy(global_stores)

    beam_width = 10  # user configurable
    time_limit = 600  # max seconds
        
    if not weights:
        weights = {
            'coverage': [1, 2, 3, 5, 8], 
            'variety': [1, 2, 3, 5, 8], 
            'price_efficiency': [0.1, 0.5, 1, 2, 3, 5, 8, 10, 14], 
            'store_penalty': [5, 10, 15, 25, 40]
        }

    num_weight_configs = weights['coverage'].__len__() * weights['variety'].__len__() * weights['price_efficiency'].__len__() * weights['store_penalty'].__len__()
    # Optional runtime estimate
    estimated_sec = estimate_beam_runtime(desired_cards, stores, beam_width, num_weight_configs)
    print(f"Estimated runtime for beam search: {estimated_sec:.1f} sec")

    #print(cart)

    results = search_multiple_weight_configs(
        desired_cards,
        stores,
        weights,
        beam_width,
        time_limit
    )

    print_cart(results["best_price_cart"])
    print_cart(results["fewest_stores_cart"])
    print_cart(results["balanced_cart"])

    end = time.time()
    print("calculated stores in " + str(end - scrape) + " seconds")
    '''
    driver = get_driver()
    response = str(input("Please select which cart you like: "))
    if response == "1":
        add_potential_cart_to_cart(driver,results["best_price_cart"])
    if response == "2":
        add_potential_cart_to_cart(driver,results["fewest_stores_cart"])
    if response == "3":
        add_potential_cart_to_cart(driver,results["balanced_cart"])
    release_driver(driver)
    '''
    return results

def main(argv):
    want_file_location = ""
    headless = False

    try:
        opts, args = getopt.getopt(argv,"w:h",["want-file-location=","headless-flag"])
    except getopt.GetoptError:
        print('tcg_player_searcher.py -w <want-file-location> -h <headless-flag>')
        print("want-file-location is the file location for a list of card names (in a text file) that you're looking to find for the store")
        print("headless-flag is the Selenium/Chrome flag to run headless.")
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-w", "--want-file-location"):
            want_file_location = arg
        if opt in ("-h", "--headless-flag"):
            #TODO doesnt work yet
            headless = True 

    if not want_file_location:
        print("using default want file")
        want_file_location = "wanted.txt"
        #sys.exit(2)

    load_dotenv()

    desired_cards = []
    #if want_file_location:
    #    desired_cards = load_desired_cards_from_file(want_file_location)
    app = QApplication(sys.argv)
    win = InputWindow()
    win.show()

    '''

    driver = get_driver()
    shutdown_driver_pool()
    #get which cart the user likes
    response = str(input("Please select which cart you like: "))
    if response == "1":
        add_potential_cart_to_cart(driver,results["best_price_cart"])
    if response == "2":
        add_potential_cart_to_cart(driver,results["fewest_stores_cart"])
    if response == "3":
        add_potential_cart_to_cart(driver,results["balanced_cart"])
    release_driver(driver)
    #wait for the user to check out or copy cart or something
    input("Press enter when finished.")
    print("cleaning up")
    shutdown_driver_pool()'''
    sys.exit(app.exec())
    shutdown_driver_pool()

if __name__ == "__main__":
    main(sys.argv[1:])