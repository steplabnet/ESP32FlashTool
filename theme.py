"""
Stile grafico comune delle GUI, ispirato a Fluent Design (Windows 11): sfondo
grigio chiaro come Mica, riquadri piatti con un bordo sottile e angoli da 8 px,
controlli con angoli da 4 px e il bordo inferiore più scuro (elevazione),
campi con la linea in basso che diventa blu col fuoco, accento blu di Windows.

Tk non sa rendere trasparenti i widget: le forme sono disegnate in immagini
generate all'avvio, già fuse con il colore su cui stanno: gli angoli devono
combaciare con quello che c'è dietro. Ogni widget arrotondato esiste quindi in
due varianti: una per l'interno dei riquadri (CARD) e una per lo sfondo della
finestra (BG).

apply(root) va chiamata subito dopo aver creato la finestra principale, prima
dei widget. Stili aggiuntivi:
    Primary.TButton   pulsante principale, colore d'accento (fuori dai riquadri)
    Accent.TButton    come Primary, alto quanto i pulsanti normali
    Card.TFrame       riquadro (vedi card()); Inner.TFrame: gruppo di widget al suo interno
    Card.TLabel       etichetta dentro un riquadro (Card.Muted.TLabel, Card.TRadiobutton)
    Page.TButton      pulsante fuori dai riquadri (TButton è per l'interno)
    Page.TEntry       campo fuori dai riquadri (anche Page.TCombobox)
    Muted.TLabel      testo secondario grigio
    Status.TLabel     riga di stato sotto la barra di avanzamento
"""

import math
import struct
import sys
import tkinter as tk
import webbrowser
import zlib
from pathlib import Path
from tkinter import font as tkfont, ttk

LOGO_FILE = "logo-200x40-1.png"  # in basso a destra, vedi brand()
WEBSITE = "www.steplab.net"

BG = "#f3f3f3"          # sfondo della finestra (Mica)
CARD = "#fbfbfb"        # interno dei riquadri
STROKE = "#e5e5e5"      # bordo di riquadri e controlli
STROKE_BOTTOM = "#cdcdcd"  # bordo inferiore dei controlli (elevazione)
STRONG = "#8a8a8a"      # linea dei campi, cerchi e interruttori spenti
DISABLED_STROKE = "#c8c8c8"
FIELD = "#ffffff"       # campi, elenchi e tabelle
CONTROL = "#fdfdfd"     # pulsanti e combobox in sola lettura
CONTROL_HOVER = "#f6f6f6"
CONTROL_PRESSED = "#f1f1f1"
CONTROL_DISABLED = "#f5f5f5"
SUBTLE_HOVER = "#eaeaea"  # sotto le voci delle schede col mouse sopra
TEXT = "#1b1b1b"
MUTED = "#616161"
ACCENT = "#005fb8"
ACCENT_HOVER = "#1a6fbf"
ACCENT_PRESSED = "#337fc6"
ACCENT_SOFT = "#e0ebf6"  # selezione negli elenchi
DISABLED_TEXT = "#a0a0a0"
ERROR = "#c42b1c"
LOG_BG = "#202020"
LOG_TEXT = "#d6d6d6"

FONT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
MONO_FAMILY = "Consolas"

CARD_RADIUS = 8
CONTROL_RADIUS = 4
CARD_PAD = 16   # spazio fra il bordo del riquadro e il contenuto
TITLE_SPACE = 30  # altezza riservata al titolo del riquadro


# ── Disegno delle immagini ────────────────────────────────────────────────────

def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _hex(color):
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in color)


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _clamp(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _sdf(px, py, x0, y0, x1, y1, r):
    """Distanza con segno dal rettangolo arrotondato (negativa dentro)."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    qx = abs(px - cx) - (x1 - x0) / 2 + r
    qy = abs(py - cy) - (y1 - y0) / 2 + r
    outside = math.hypot(max(qx, 0), max(qy, 0))
    return outside + min(max(qx, qy), 0) - r


def _keep(root, image):
    root._theme_images.append(image)  # senza riferimento Tk perderebbe l'immagine
    return image


def _shape(root, w, h, radius, fill, border=None, border_bottom=None, underline=None,
           margin=(0, 0, 0, 0), bg=BG, dot=None, shape_width=None):
    """Immagine w×h di una forma arrotondata a tinta unita fusa sullo sfondo bg.

    border: colore del bordo da 1 px; border_bottom: colore del bordo in basso,
    più scuro per dare elevazione; underline: (colore, spessore) linea sul lato
    inferiore, come nei campi di testo; margin: spazio attorno alla forma
    (sinistra, sopra, destra, sotto); dot: (raggio, colore[, x]) pallino, al
    centro se x manca; shape_width: larghezza della forma se più stretta
    dell'immagine (a sinistra).
    """
    bg_c, fill_c = _rgb(bg), _rgb(fill)
    border_c = _rgb(border) if border else None
    bottom_c = _rgb(border_bottom) if border_bottom else border_c
    ml, mt, mr, mb = margin
    x0, y0 = ml, mt
    x1 = ml + shape_width if shape_width else w - mr
    y1 = h - mb
    r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)

    rows = []
    for y in range(h):
        py = y + 0.5
        row = []
        for x in range(w):
            px = x + 0.5
            c = bg_c
            d = _sdf(px, py, x0, y0, x1, y1, r)
            cover = _clamp(0.5 - d)
            if cover > 0:
                color = fill_c
                if dot:
                    dr, dc = dot[:2]
                    dx = dot[2] if len(dot) > 2 else (x0 + x1) / 2
                    dd = math.hypot(px - dx, py - (y0 + y1) / 2) - dr
                    color = _mix(color, _rgb(dc), _clamp(0.5 - dd))
                if border_c:
                    edge = _mix(border_c, bottom_c, _clamp(py - (y1 - 2)))
                    ring = cover - _clamp(0.5 - (d + 1))
                    color = _mix(color, edge, _clamp(ring / cover))
                if underline:
                    line_c, line_w = underline
                    color = _mix(color, _rgb(line_c), _clamp(y + 1 - (y1 - line_w)))
                c = _mix(c, color, cover)
            row.append(_hex(c))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=root, width=w, height=h)
    image.put(" ".join(rows))
    return _keep(root, image)


def _chevron(root, color, size=12):
    """Freccia a V delle combobox; i pixel vuoti restano trasparenti.

    I bordi sfumati sono fusi su CONTROL: sui fondi chiari dei campi non si notano.
    """
    c, field = _rgb(color), _rgb(CONTROL)
    (ax, ay), (bx, by), (cx, cy) = (2.5, 4.5), (6, 8), (9.5, 4.5)

    def segment(px, py, x0, y0, x1, y1):
        vx, vy = x1 - x0, y1 - y0
        t = _clamp(((px - x0) * vx + (py - y0) * vy) / (vx * vx + vy * vy))
        return math.hypot(px - x0 - t * vx, py - y0 - t * vy)

    image = tk.PhotoImage(master=root, width=size, height=size)
    for y in range(size):
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            d = min(segment(px, py, ax, ay, bx, by), segment(px, py, bx, by, cx, cy))
            cover = _clamp(1.1 - d)
            if cover > 0:
                image.put(_hex(_mix(field, c, cover)), (x, y))
    return _keep(root, image)


STRETCH = 128  # lato minimo della parte centrale delle immagini stirate, vedi _widen()


def _widen(image, border):
    """Copia di image con la parte centrale ripetuta fino a STRETCH pixel.

    Tk stira le immagini degli elementi ripetendo la parte centrale come una
    piastrella: con un centro di pochi pixel un riquadro grande richiede decine
    di migliaia di copie a ogni ridisegno e la finestra diventa lentissima. Le
    forme sono a tinta unita, quindi ripetere il centro non cambia il disegno.
    """
    w, h = image.width(), image.height()
    left, top, right, bottom = border
    cw, ch = w - left - right, h - top - bottom
    # una dimensione senza centro non viene stirata: resta com'è
    new_cw = max(cw, STRETCH) if cw > 0 else cw
    new_ch = max(ch, STRETCH) if ch > 0 else ch
    if (new_cw, new_ch) == (cw, ch):
        return image
    W, H = left + new_cw + right, top + new_ch + bottom
    big = tk.PhotoImage(master=image.tk, width=W, height=H)
    # nove parti: colonne e righe di sorgente e destinazione (bordo, centro, bordo)
    cols = ((0, left, 0, left), (left, w - right, left, W - right), (w - right, w, W - right, W))
    rows = ((0, top, 0, top), (top, h - bottom, top, H - bottom), (h - bottom, h, H - bottom, H))
    for sx0, sx1, dx0, dx1 in cols:
        for sy0, sy1, dy0, dy1 in rows:
            if sx1 > sx0 and sy1 > sy0:
                big.tk.call(big, "copy", image, "-from", sx0, sy0, sx1, sy1,
                            "-to", dx0, dy0, dx1, dy1)
    return big


def _element(style, name, images, border, sticky="nsew"):
    """Elemento immagine; images = [(stati, immagine), ...], il primo è il normale.

    border: le parti dell'immagine che non vengono stirate (angoli e bordi); deve
    lasciare almeno una riga e una colonna centrali. padding 0: lo spazio attorno
    al contenuto lo decide il padding dello stile, non il bordo dell'immagine.
    """
    # la misura minima resta quella dell'immagine originale anche se _widen la ingrandisce
    size = {"width": images[0][1].width(), "height": images[0][1].height()}
    if sticky:
        if isinstance(border, int):
            border = (border,) * 4
        elif len(border) == 2:
            border = border * 2
        images = [(states, _keep(style.master, _widen(image, border)))
                  for states, image in images]
    default = images[0][1]
    specs = [(*states, image) for states, image in images[1:]]
    style.element_create(name, "image", default, *specs, border=border, padding=0,
                         sticky=sticky, **size)


def _button_layout(element):
    return [(element, {"sticky": "nswe", "children": [
        ("Button.padding", {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "nswe"})]})]})]


def _semibold(families, family, size):
    name = f"{family} Semibold"
    return (name, size) if name in families else (family, size, "bold")


def caption(window):
    """Barra del titolo di Windows 11 dello stesso colore dello sfondo."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        r, g, b = _rgb(BG)
        color = ctypes.c_uint(r | g << 8 | b << 16)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # 35: DWMWA_CAPTION_COLOR
            hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
    except (AttributeError, OSError):
        pass  # fuori da Windows o prima di Windows 11


# ── Tema ──────────────────────────────────────────────────────────────────────

def apply(root):
    families = set(tkfont.families(root))
    family = next((f for f in FONT_FAMILIES if f in families), "TkDefaultFont")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    base = (family, 10)
    semibold = _semibold(families, family, 10)
    root._theme_images = []

    root.configure(background=BG)
    # widget tk classici (elenchi, dialoghi, testo); non "*Font" o "*Background":
    # varrebbero anche per i widget ttk e ne scavalcherebbero lo stile
    for widget in ("Toplevel", "Frame", "Label", "Button", "Listbox", "Text"):
        root.option_add(f"*{widget}.background", BG)
        root.option_add(f"*{widget}.foreground", TEXT)
        root.option_add(f"*{widget}.font", base)
    root.option_add("*Listbox.background", FIELD)
    root.option_add("*Listbox.relief", "flat")
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*Listbox.selectForeground", TEXT)
    root.option_add("*Listbox.disabledForeground", DISABLED_TEXT)
    root.option_add("*Listbox.activeStyle", "none")
    root.option_add("*Button.relief", "flat")
    root.option_add("*Button.background", CONTROL)
    root.option_add("*Button.activeBackground", CONTROL_HOVER)
    root.option_add("*Button.borderWidth", 0)
    root.option_add("*Button.padX", 12)
    root.option_add("*Button.padY", 5)
    # elenco a tendina delle combobox
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.font", base)

    style = ttk.Style(root)
    style.theme_use("clam")  # l'unico tema di base che lascia cambiare tutti i colori

    style.configure(".", background=BG, foreground=TEXT, font=base,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG, troughcolor=BG,
                    focuscolor=ACCENT, selectbackground=ACCENT_SOFT, selectforeground=TEXT,
                    fieldbackground=FIELD, insertcolor=TEXT, relief="flat")
    style.map(".", foreground=[("disabled", DISABLED_TEXT)])

    # riquadri: piatti, con il bordo sottile e senza ombra
    r = CARD_RADIUS
    card = _shape(root, 2 * r + 4, 2 * r + 4, r, CARD, border=STROKE)
    _element(style, "fluent.card", [((), card)], border=r + 1)
    style.layout("Card.TFrame", [("fluent.card", {"sticky": "nswe"})])
    style.configure("Card.TFrame", background=CARD)

    style.configure("Divider.TFrame", background=STROKE)

    # testi
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 9))
    style.configure("Status.TLabel", background=BG, foreground=MUTED)
    style.configure("Link.TLabel", background=BG, foreground=ACCENT, font=(family, 9))
    style.configure("LinkHover.TLabel", background=BG, foreground=ACCENT_HOVER,
                    font=(family, 9, "underline"))
    style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT,
                    font=_semibold(families, family, 11))
    for name in ("TLabel", "Muted.TLabel"):
        style.configure(f"Card.{name}", background=CARD)
    style.configure("Card.Muted.TLabel", foreground=MUTED, font=(family, 9))
    style.configure("TLabelframe", background=BG)
    style.configure("TLabelframe.Label", background=BG, font=semibold)

    style.configure("Inner.TFrame", background=CARD)  # gruppo di widget dentro un riquadro

    # pulsanti: quasi bianchi, bordo inferiore più scuro; TButton nei riquadri,
    # Page.TButton fuori. Le stesse immagini fanno le combobox in sola lettura
    r = CONTROL_RADIUS
    control = {}
    for key, bg in (("card", CARD), ("page", BG)):
        control[key] = {
            "rest": _shape(root, 24, 32, r, CONTROL, border=STROKE,
                           border_bottom=STROKE_BOTTOM, bg=bg),
            "disabled": _shape(root, 24, 32, r, CONTROL_DISABLED, border=STROKE, bg=bg),
            "pressed": _shape(root, 24, 32, r, CONTROL_PRESSED, border=STROKE, bg=bg),
            "hover": _shape(root, 24, 32, r, CONTROL_HOVER, border=STROKE,
                            border_bottom=STROKE_BOTTOM, bg=bg),
        }
    for prefix, key, bg in (("", "card", CARD), ("Page.", "page", BG)):
        images = control[key]
        element = f"fluent.{key}button"
        _element(style, element, [((), images["rest"]),
                                  (("disabled",), images["disabled"]),
                                  (("pressed",), images["pressed"]),
                                  (("active",), images["hover"])], border=r + 1)
        style.layout(f"{prefix}TButton", _button_layout(element))
        style.configure(f"{prefix}TButton", background=bg, foreground=TEXT, padding=(14, 6),
                        anchor="center", font=base)
        style.map(f"{prefix}TButton", foreground=[("disabled", DISABLED_TEXT),
                                                  ("pressed", MUTED)])

    # pulsante principale: colore d'accento, sullo sfondo della finestra. Primary è
    # quello grande in fondo alla finestra, Accent ha l'altezza dei pulsanti normali
    for name, h, padding, button_font in (
            ("Primary", 40, (24, 9), _semibold(families, family, 11)),
            ("Accent", 32, (14, 6), base)):
        images = [
            ((), _shape(root, 24, h, r, ACCENT, border="#1a6bbb", border_bottom="#003e78")),
            (("disabled",), _shape(root, 24, h, r, DISABLED_STROKE)),
            (("pressed",), _shape(root, 24, h, r, ACCENT_PRESSED)),
            (("active",), _shape(root, 24, h, r, ACCENT_HOVER, border="#2f7bc4",
                                 border_bottom="#0c4b85")),
        ]
        element = f"fluent.{name.lower()}"
        _element(style, element, images, border=r + 1)
        style.layout(f"{name}.TButton", _button_layout(element))
        style.configure(f"{name}.TButton", foreground="#ffffff", padding=padding,
                        font=button_font, anchor="center")
        style.map(f"{name}.TButton", foreground=[("disabled", "#ffffff"),
                                                 ("pressed", "#dce8f5")])

    # campi: bianchi, linea grigia in basso che col fuoco diventa blu e più spessa.
    # Le combobox in sola lettura invece sembrano pulsanti, come in Windows 11
    for prefix, key, bg in (("", "card", CARD), ("Page.", "page", BG)):
        buttons = control[key]
        element = f"fluent.{key}field"
        _element(style, element, [
            ((), _shape(root, 24, 32, r, FIELD, border=STROKE, underline=(STRONG, 1), bg=bg)),
            (("disabled",), buttons["disabled"]),
            (("readonly", "pressed"), buttons["pressed"]),
            (("readonly", "active"), buttons["hover"]),
            (("readonly",), buttons["rest"]),
            (("focus",), _shape(root, 24, 32, r, FIELD, border=STROKE,
                                underline=(ACCENT, 2), bg=bg)),
        ], border=r + 1)
        style.layout(f"{prefix}TEntry", [(element, {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})])
        # la freccia sta dentro il padding, così non copre l'angolo arrotondato
        style.layout(f"{prefix}TCombobox", [(element, {"sticky": "nswe", "children": [
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("fluent.chevron", {"side": "right", "sticky": ""}),
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])
        for name in ("TEntry", "TCombobox"):
            style.configure(f"{prefix}{name}", fieldbackground=FIELD, background=FIELD,
                            foreground=TEXT, padding=(10, 6, 10, 6))
            style.map(f"{prefix}{name}",
                      selectbackground=[("readonly", "active", CONTROL_HOVER),
                                        ("readonly", CONTROL)],
                      selectforeground=[("readonly", TEXT)])
    _element(style, "fluent.chevron", [((), _chevron(root, MUTED)),
                                       (("disabled",), _chevron(root, DISABLED_TEXT))],
             border=0, sticky="")

    # elenchi e tabelle: come i campi, ma senza la linea in basso
    box = _shape(root, 24, 32, r, FIELD, border=STROKE, bg=CARD)
    _element(style, "fluent.box", [((), box)], border=r + 1)
    style.layout("Field.TFrame", [("fluent.box", {"sticky": "nswe"})])

    # scelte: cerchio grigio, pieno di blu con un pallino bianco quando è selezionato
    for prefix, bg in (("", BG), ("Card.", CARD)):
        def radio(fill, border=None, dot=None):
            return _shape(root, 28, 22, 10, fill, border=border, shape_width=20,
                          margin=(0, 1, 0, 1), bg=bg, dot=dot)
        element = f"fluent.{prefix.lower()}radio"
        _element(style, element, [
            ((), radio(CONTROL, STRONG)),
            (("disabled", "selected"), radio(DISABLED_STROKE, dot=(4, "#ffffff"))),
            (("disabled",), radio(CONTROL_DISABLED, DISABLED_STROKE)),
            (("selected", "pressed"), radio(ACCENT_PRESSED, dot=(3, "#ffffff"))),
            (("selected", "active"), radio(ACCENT_HOVER, dot=(5, "#ffffff"))),
            (("selected",), radio(ACCENT, dot=(4, "#ffffff"))),
            (("active",), radio(SUBTLE_HOVER, STRONG)),
        ], border=0, sticky="")
        style.layout(f"{prefix}TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [
            (element, {"side": "left", "sticky": ""}),
            ("Radiobutton.label", {"side": "left", "sticky": "nswe"})]})])
        style.configure(f"{prefix}TRadiobutton", background=bg, padding=(0, 3))
        style.map(f"{prefix}TRadiobutton", background=[("active", bg)])

    # interruttore: capsula col bordo grigio, piena di blu quando è acceso; il
    # pomello si ingrandisce col mouse sopra
    def switch(fill, knob, x, size=6, border=None):
        return _shape(root, 42, 22, 10, fill, border=border, margin=(1, 1, 1, 1), bg=CARD,
                      dot=(size, knob, x))
    _element(style, "fluent.switch", [
        ((), switch(CONTROL, MUTED, 11, border=STRONG)),
        (("disabled", "selected"), switch(DISABLED_STROKE, "#ffffff", 31)),
        (("disabled",), switch(CONTROL_DISABLED, DISABLED_STROKE, 11, border=DISABLED_STROKE)),
        (("selected", "active"), switch(ACCENT_HOVER, "#ffffff", 31, 7)),
        (("selected",), switch(ACCENT, "#ffffff", 31)),
        (("active",), switch(CONTROL_HOVER, MUTED, 11, 7, border=STRONG)),
    ], border=0, sticky="")
    style.layout("Switch.TCheckbutton", [("fluent.switch", {"sticky": ""})])
    style.configure("Switch.TCheckbutton", background=CARD, padding=0)
    style.map("Switch.TCheckbutton", background=[("active", CARD)])

    # schede: voci di testo, la scelta ha sotto una barretta blu (SelectorBar)
    _element(style, "fluent.selector", [
        ((), _shape(root, 16, 32, r, BG)),
        (("active",), _shape(root, 16, 32, r, SUBTLE_HOVER)),
    ], border=r + 1)
    _element(style, "fluent.pill", [
        ((), _shape(root, 16, 3, 1.5, BG)),
        (("selected", "active"), _shape(root, 16, 3, 1.5, ACCENT, bg=SUBTLE_HOVER)),
        (("selected",), _shape(root, 16, 3, 1.5, ACCENT)),
        (("active",), _shape(root, 16, 3, 1.5, SUBTLE_HOVER, bg=SUBTLE_HOVER)),
    ], border=0, sticky="")
    style.layout("Selector.TRadiobutton", [("fluent.selector", {"sticky": "nswe", "children": [
        ("Toolbutton.padding", {"sticky": "nswe", "children": [
            ("fluent.pill", {"side": "bottom", "sticky": ""}),
            ("Toolbutton.label", {"side": "top", "sticky": "nswe"})]})]})])
    style.configure("Selector.TRadiobutton", background=BG, foreground=MUTED,
                    padding=(12, 7, 12, 3), anchor="center", font=base)
    style.map("Selector.TRadiobutton", background=[("active", BG)],
              foreground=[("selected", TEXT), ("active", TEXT)])

    # avanzamento: linea sottile grigia, barra blu arrotondata da 3 px
    trough = _shape(root, 16, 4, 0.5, STRONG, margin=(0, 1.5, 0, 1.5))
    pbar = _shape(root, 16, 4, 1.5, ACCENT, margin=(0, 0.5, 0, 0.5))
    _element(style, "fluent.Horizontal.Progressbar.trough", [((), trough)], border=(2, 0))
    _element(style, "fluent.Horizontal.Progressbar.pbar", [((), pbar)], border=(2, 0))
    style.layout("Horizontal.TProgressbar", [("fluent.Horizontal.Progressbar.trough", {
        "sticky": "nswe", "children": [
            ("fluent.Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])
    style.configure("Horizontal.TProgressbar", thickness=4)

    # barre di scorrimento: cursore sottile che si allarga col mouse sopra
    for prefix, bg, thumb in (("", FIELD, STRONG), ("Page.", BG, STRONG),
                              ("Dark.", LOG_BG, "#7a7a7a")):
        thin = _shape(root, 12, 28, 1.5, thumb, margin=(5, 2, 4, 2), bg=bg)
        wide = _shape(root, 12, 28, 3, thumb, margin=(3, 2, 3, 2), bg=bg)
        element = f"fluent.{prefix}Vertical.Scrollbar.thumb"
        _element(style, element, [((), thin), (("pressed",), wide), (("active",), wide)],
                 border=(6, 7))
        style.layout(f"{prefix}Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "sticky": "ns", "children": [(element, {"expand": "1", "sticky": "nswe"})]})])
        style.configure(f"{prefix}Vertical.TScrollbar", troughcolor=bg, background=bg,
                        bordercolor=bg, lightcolor=bg, darkcolor=bg, width=12)

    # tabelle
    style.layout("Treeview", [("fluent.box", {"sticky": "nswe", "children": [
        ("Treeview.padding", {"sticky": "nswe", "children": [
            ("Treeview.treearea", {"sticky": "nswe"})]})]})])
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    rowheight=30, padding=4)
    style.map("Treeview", background=[("selected", ACCENT_SOFT)],
              foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, font=semibold,
                    borderwidth=0, relief="flat", padding=(8, 6),
                    bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD)
    style.map("Treeview.Heading", background=[("active", CONTROL_HOVER)])

    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=10, background=BG, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG, gripcount=0)
    return style


# ── Componenti ────────────────────────────────────────────────────────────────

def resource(name):
    """Percorso di un file distribuito con il programma (nell'exe: --add-data)."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return Path(base) / name


def _read_png(path):
    """(larghezza, altezza, pixel RGBA) di un PNG a 8 bit, RGB o RGBA, non interlacciato."""
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            w, h, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    if depth != 8 or color_type not in (2, 6) or interlace:
        raise ValueError(f"{path}: formato PNG non gestito")
    bpp = 4 if color_type == 6 else 3
    stride = w * bpp
    raw = zlib.decompress(idat)
    pixels = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):  # filtri PNG: 1 sub, 2 up, 3 average, 4 paeth
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        if bpp == 3:
            pixels += b"".join(bytes(line[i:i + 3]) + b"\xff" for i in range(0, stride, 3))
        else:
            pixels += line
        prev = line
    return w, h, pixels


def logo(parent, scale=2, bg=BG):
    """Etichetta con il logo ridotto di scale volte, fuso sullo sfondo bg.

    Tk riduce le immagini saltando i pixel (bordi seghettati): qui ogni pixel
    è la media di un blocco scale×scale. Ritorna None se il file non si legge.
    """
    try:
        w, h, pixels = _read_png(resource(LOGO_FILE))
    except (OSError, ValueError, zlib.error):
        return None
    bg_c = _rgb(bg)
    n = scale * scale
    rows = []
    for y in range(h // scale):
        row = []
        for x in range(w // scale):
            r = g = b = alpha = 0
            for dy in range(scale):
                for dx in range(scale):
                    i = ((y * scale + dy) * w + x * scale + dx) * 4
                    a = pixels[i + 3]
                    r += pixels[i] * a
                    g += pixels[i + 1] * a
                    b += pixels[i + 2] * a
                    alpha += a
            # media dei colori pesata con la trasparenza, poi sopra lo sfondo
            cover = alpha / (255 * n)
            color = [(s / alpha if alpha else 0) * cover + k * (1 - cover)
                     for s, k in zip((r, g, b), bg_c)]
            row.append("#%02x%02x%02x" % tuple(int(round(v)) for v in color))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=parent, width=w // scale, height=h // scale)
    image.put(" ".join(rows))
    label = ttk.Label(parent, image=image, background=bg)
    label.image = image  # senza riferimento Tk perderebbe l'immagine
    return label


def brand(parent):
    """Indirizzo del sito, cliccabile, e logo affiancati: per l'angolo in basso a destra."""
    frame = ttk.Frame(parent)
    link = ttk.Label(frame, text=WEBSITE, style="Link.TLabel", cursor="hand2")
    link.pack(side="left")
    link.bind("<Button-1>", lambda _e: webbrowser.open(f"https://{WEBSITE}"))
    link.bind("<Enter>", lambda _e: link.configure(style="LinkHover.TLabel"))
    link.bind("<Leave>", lambda _e: link.configure(style="Link.TLabel"))
    image = logo(frame)
    if image:
        image.pack(side="left", padx=(12, 0))
    return frame


def card(parent, title=None):
    """Riquadro arrotondato con il bordo sottile, con il titolo in alto a sinistra.

    Il titolo è posizionato con place, così dentro il riquadro si possono usare
    sia grid sia pack; il padding superiore gli lascia spazio. Le coordinate di
    place partono dall'interno del padding, per questo sono negative.
    """
    top = CARD_PAD + (TITLE_SPACE if title else 0)
    frame = ttk.Frame(parent, style="Card.TFrame", padding=(CARD_PAD, top, CARD_PAD, CARD_PAD))
    if title:
        frame.title_y = -(TITLE_SPACE + 4)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").place(x=0, y=frame.title_y)
    return frame


def card_switch(card_frame, variable, command):
    """Interruttore a destra del titolo di un riquadro; ritorna il widget."""
    switch = ttk.Checkbutton(card_frame, style="Switch.TCheckbutton", variable=variable,
                             command=command, cursor="hand2", takefocus=False)
    switch.place(relx=1.0, x=0, y=card_frame.title_y, anchor="ne")
    return switch


class ScrollArea(ttk.Frame):
    """Area con barra di scorrimento verticale, visibile solo se il contenuto non ci sta.

    I widget vanno creati in .inner. Se la finestra è più alta del contenuto,
    .inner si allunga fino in fondo: le righe con peso ricevono lo spazio in più.
    """

    WHEEL_STEP = 3  # righe di yscrollincrement per scatto della rotella

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, borderwidth=0,
                                yscrollincrement=20)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="Page.Vertical.TScrollbar")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self._resize())
        self.canvas.bind("<Configure>", lambda _e: self._resize())
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        # la rotella sopra una combobox scorre la pagina invece di cambiarne la scelta
        self.unbind_class("TCombobox", "<MouseWheel>")

    def fit(self):
        """Chiede lo spazio per mostrare tutto il contenuto (poi center() lo limita)."""
        self.update_idletasks()
        self.canvas.configure(width=self.inner.winfo_reqwidth(),
                              height=self.inner.winfo_reqheight())

    def _resize(self):
        width = self.canvas.winfo_width()
        height = max(self.inner.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _scrolled(self, first, last):
        self.scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid()

    def _wheel(self, event):
        widget = event.widget
        if not isinstance(widget, tk.Misc) or not str(widget).startswith(str(self.canvas)):
            return
        # log ed elenchi scorrono per conto loro
        if widget.winfo_class() in ("Text", "Listbox", "Treeview"):
            return
        if self.scrollbar.winfo_ismapped():
            self.canvas.yview_scroll(-self.WHEEL_STEP * round(event.delta / 120), "units")


class Tabs(ttk.Frame):
    """Schede scelte con una barra di voci in alto a sinistra (SelectorBar).

    Le pagine stanno tutte nella stessa cella della griglia, una sopra l'altra:
    la scheda scelta passa in primo piano. Così l'area è alta quanto la pagina
    più alta e la finestra non cambia misura passando da una scheda all'altra.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        # il testo della prima voce allineato al bordo dei riquadri delle pagine
        self.bar = ttk.Frame(self)
        self.bar.grid(row=0, column=0, sticky="w", padx=(8, 0), pady=(8, 0))
        self.current = tk.StringVar()
        self.pages = {}

    def add(self, name, scroll=True):
        """Nuova scheda; ritorna il riquadro in cui creare i widget della pagina.

        scroll: la pagina scorre se la finestra è troppo bassa; senza, il
        riquadro si allunga fino in fondo (per il log, che scorre da sé).
        """
        if scroll:
            page = ScrollArea(self)
            content = page.inner
        else:
            page = content = ttk.Frame(self)
        page.grid(row=1, column=0, sticky="nsew")
        self.pages[name] = page
        ttk.Radiobutton(self.bar, text=name, value=name, variable=self.current,
                        style="Selector.TRadiobutton", takefocus=False,
                        command=lambda: self.select(name)).pack(side="left")
        if len(self.pages) == 1:
            self.select(name)
        else:
            self.pages[self.current.get()].tkraise()
        return content

    def select(self, name):
        self.current.set(name)
        self.pages[name].tkraise()

    def fit(self):
        """Prepara le pagine che scorrono: chiedono lo spazio di tutto il contenuto."""
        for page in self.pages.values():
            if isinstance(page, ScrollArea):
                page.fit()


def field_box(parent):
    """Cornice arrotondata bianca per un Listbox: ritorna il riquadro in cui crearlo."""
    return ttk.Frame(parent, style="Field.TFrame", padding=6)


def log_widget(parent, height=10):
    """Area di log scura e arrotondata; ritorna (riquadro, testo)."""
    root = parent.winfo_toplevel()
    if not hasattr(root, "_log_panel"):
        r = CARD_RADIUS
        root._log_panel = _shape(root, 2 * r + 4, 2 * r + 4, r, LOG_BG, border="#2b2b2b")
        style = ttk.Style(root)
        _element(style, "fluent.log", [((), root._log_panel)], border=r + 1)
        style.layout("Log.TFrame", [("fluent.log", {"sticky": "nswe"})])
        style.configure("Log.TFrame", background=LOG_BG)
    box = ttk.Frame(parent, style="Log.TFrame", padding=(8, 8, 4, 8))
    text = tk.Text(box, height=height, state="disabled", wrap="word", relief="flat",
                   borderwidth=0, highlightthickness=0, padx=8, pady=4,
                   background=LOG_BG, foreground=LOG_TEXT, insertbackground=LOG_TEXT,
                   selectbackground="#264f78", font=(MONO_FAMILY, 9))
    scroll = ttk.Scrollbar(box, orient="vertical", command=text.yview,
                           style="Dark.Vertical.TScrollbar")
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return box, text


# ── Posizione della finestra ──────────────────────────────────────────────────

def _foreground():
    """Finestra in primo piano, letta all'avvio: quella da cui è stato lanciato il
    programma (Esplora risorse, barra delle applicazioni, terminale)."""
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except (AttributeError, OSError):
        return None


# letta all'importazione, prima che si apra una finestra Tk: l'exe in un unico
# file impiega alcuni secondi a partire e intanto il mouse può spostarsi altrove
LAUNCHER = _foreground()


def work_area(root, at=None):
    """(x, y, larghezza, altezza) dell'area utile del monitor che contiene il punto
    at (x, y), o di quello della finestra da cui è stato lanciato il programma, o
    di quello su cui c'è il mouse.

    Esclude la barra delle applicazioni; fuori da Windows lo schermo principale.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        monitor = None
        if at:
            monitor = user32.MonitorFromPoint(wintypes.POINT(*at), 2)  # MONITOR_DEFAULTTONEAREST
        elif LAUNCHER and user32.IsWindow(LAUNCHER):
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(LAUNCHER, name, 64)
            # il desktop copre tutti i monitor: lì conta il punto del doppio clic
            if name.value not in ("Progman", "WorkerW"):
                monitor = user32.MonitorFromWindow(LAUNCHER, 2)
        if not monitor:
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            monitor = user32.MonitorFromPoint(point, 2)
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except (AttributeError, OSError):
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def center(root):
    """Centra la finestra sul monitor in uso, ridotta se non ci sta.

    Va chiamata dopo aver creato i widget, prima di mainloop.
    """
    root.withdraw()  # nascosta finché non è al suo posto
    root.update_idletasks()
    left, top, width, height = work_area(root)
    # la cornice di Windows (bordi e barra del titolo) non è compresa in winfo_req*
    frame_w, frame_h = 16, 40
    min_w, min_h = root.minsize()
    min_w, min_h = min(min_w, width - frame_w), min(min_h, height - frame_h)
    root.minsize(min_w, min_h)
    w = min(max(root.winfo_reqwidth(), min_w), width - frame_w)
    h = min(max(root.winfo_reqheight(), min_h), height - frame_h)
    x = left + (width - w - frame_w) // 2
    y = top + (height - h - frame_h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    caption(root)
    root.deiconify()


def place_over(window, parent):
    """Centra window sulla finestra parent, senza uscire dal monitor di quest'ultima."""
    window.update_idletasks()
    w, h = window.winfo_reqwidth(), window.winfo_reqheight()
    owner = parent.winfo_toplevel()
    if owner.winfo_viewable():
        cx = owner.winfo_rootx() + owner.winfo_width() // 2
        cy = owner.winfo_rooty() + owner.winfo_height() // 2
        left, top, width, height = work_area(window, (cx, cy))
    else:
        left, top, width, height = work_area(window)
        cx, cy = left + width // 2, top + height // 2
    frame_w, frame_h = 16, 40  # cornice di Windows, vedi center()
    x = max(left, min(cx - (w + frame_w) // 2, left + width - w - frame_w))
    y = max(top, min(cy - (h + frame_h) // 2, top + height - h - frame_h))
    window.geometry(f"+{x}+{y}")


# ── Finestre di dialogo ───────────────────────────────────────────────────────
# Al posto di tkinter.messagebox e simpledialog: quelle di Windows si aprono sul
# monitor principale e simpledialog le sposta sul principale se la finestra sta
# su un altro schermo. Queste si aprono al centro della finestra che le chiama.

class Dialog(tk.Toplevel):
    """Finestra modale nello stile del tema, centrata sulla finestra parent.

    Come simpledialog.Dialog: body(master) crea i widget e ritorna quello che
    riceve il fuoco, validate() e apply() vengono chiamati alla conferma.
    buttons: [(testo, valore)]; l'ultimo è il principale e risponde a Invio,
    cancel è il valore di Esc e della chiusura. Il valore scelto va in result.
    """

    def __init__(self, parent, title, buttons=(("Annulla", None), ("OK", True)), cancel=None):
        parent = parent or tk._default_root
        super().__init__(parent)
        self.withdraw()  # nascosta finché non è al suo posto
        self.title(title)
        self.configure(background=BG)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.parent = parent
        self.result = None
        self.cancel = cancel

        # contenuto in alto, pulsanti di pari larghezza in una fascia separata
        body = ttk.Frame(self, padding=(24, 22, 24, 22))
        body.pack(fill="both", expand=True)
        focus = self.body(body)
        ttk.Frame(self, style="Divider.TFrame", height=1).pack(fill="x")
        row = ttk.Frame(self, padding=(24, 16, 24, 16))
        row.pack(fill="x")
        default = buttons[-1][1]
        for i, (text, value) in enumerate(reversed(buttons)):
            ttk.Button(row, text=text, width=10,
                       style="Accent.TButton" if i == 0 else "Page.TButton",
                       command=lambda v=value: self.done(v)).pack(side="right", padx=(8, 0))
        self.bind("<Return>", lambda _e: self.done(default))
        self.bind("<Escape>", lambda _e: self.done(cancel))
        self.protocol("WM_DELETE_WINDOW", lambda: self.done(cancel))

        place_over(self, parent)
        caption(self)
        self.deiconify()
        self.grab_set()
        (focus or self).focus_set()
        self.wait_window()

    def body(self, master):
        return None

    def validate(self):
        return True

    def apply(self):
        pass

    def done(self, value):
        if value != self.cancel:
            if not self.validate():
                return
            self.result = value
            self.apply()
        else:
            self.result = value
        self.grab_release()
        self.destroy()
        self.parent.focus_set()


ICONS = {  # simbolo e colore del cerchio, come nelle InfoBar di Windows 11
    "info": ("i", ACCENT),
    "question": ("?", ACCENT),
    "warning": ("!", "#9d5d00"),
    "error": ("✕", ERROR),
}


class _Message(Dialog):
    def __init__(self, parent, title, message, icon, buttons, cancel):
        self.message, self.icon = message, icon
        super().__init__(parent, title, buttons, cancel)

    def body(self, master):
        root = self._root()
        cache = root.__dict__.setdefault("_theme_icons", {})
        symbol, color = ICONS[self.icon]
        if self.icon not in cache:
            cache[self.icon] = _shape(root, 32, 32, 16, color)
        ttk.Label(master, image=cache[self.icon], text=symbol, compound="center",
                  foreground="#ffffff", font=(tkfont.nametofont("TkDefaultFont").actual("family"),
                                              12, "bold")).pack(side="left", anchor="n")
        ttk.Label(master, text=self.message, wraplength=420, justify="left").pack(
            side="left", anchor="n", padx=(14, 0), pady=(5, 0))
        if self.icon in ("warning", "error"):
            self.bell()
        return None


def showinfo(title, message, parent=None):
    return _Message(parent, title, message, "info", [("OK", "ok")], "ok").result


def showwarning(title, message, parent=None):
    return _Message(parent, title, message, "warning", [("OK", "ok")], "ok").result


def showerror(title, message, parent=None):
    return _Message(parent, title, message, "error", [("OK", "ok")], "ok").result


def askyesno(title, message, parent=None):
    return _Message(parent, title, message, "question", [("No", False), ("Sì", True)],
                    False).result


def askyesnocancel(title, message, parent=None):
    """True, False, o None con Annulla."""
    return _Message(parent, title, message, "question",
                    [("Annulla", None), ("No", False), ("Sì", True)], None).result


def askretrycancel(title, message, parent=None):
    return _Message(parent, title, message, "warning", [("Annulla", False), ("Riprova", True)],
                    False).result


class _AskString(Dialog):
    def __init__(self, parent, title, prompt, initialvalue):
        self.prompt = prompt
        self.var = tk.StringVar(value=initialvalue)
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self.prompt, wraplength=360, justify="left").pack(anchor="w")
        entry = ttk.Entry(master, textvariable=self.var, width=40, style="Page.TEntry")
        entry.pack(fill="x", pady=(8, 0))
        entry.select_range(0, "end")
        return entry

    def apply(self):
        self.result = self.var.get()


def askstring(title, prompt, initialvalue="", parent=None):
    """Il testo inserito, o None con Annulla."""
    return _AskString(parent, title, prompt, initialvalue).result
