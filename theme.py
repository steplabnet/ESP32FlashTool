"""
Stile grafico comune delle GUI, ispirato a Liquid Glass: pulsanti a capsula,
riquadri arrotondati che galleggiano con un'ombra morbida, riflesso di luce sul
bordo superiore, angoli concentrici, accento blu "vetro colorato".

Tk non sa sfocare né rendere trasparenti i widget: il vetro è disegnato in
immagini generate all'avvio (bordo, riflesso, ombra), già fuse con il colore
su cui stanno: gli angoli devono combaciare con quello che c'è dietro. Ogni
widget arrotondato esiste quindi in due varianti: una per l'interno dei
riquadri (CARD) e una per lo sfondo della finestra (BG).

apply(root) va chiamata subito dopo aver creato la finestra principale, prima
dei widget. Stili aggiuntivi:
    Primary.TButton   pulsante principale, vetro colorato (fuori dai riquadri)
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

BG = "#eef1f6"          # sfondo della finestra
CARD = "#f5f7fb"        # interno dei riquadri
TRACK = "#e3e7ee"       # binario del controllo segmentato delle schede
FIELD = "#ffffff"       # campi, elenchi e tabelle
TEXT = "#1d1d1f"
MUTED = "#6e6e73"
ACCENT = "#0a84ff"
ACCENT_SOFT = "#d6e8ff"  # selezione negli elenchi
DISABLED_TEXT = "#a1a6ae"
LOG_BG = "#161b26"
LOG_TEXT = "#e3e8f0"

FONT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
TITLE_FAMILIES = ("Segoe UI Variable Display", "Segoe UI")
MONO_FAMILY = "Consolas"

# margini lasciati attorno alle forme per l'ombra: sinistra, sopra, destra, sotto
CARD_MARGIN = (4, 3, 4, 7)
CARD_RADIUS = 18
CARD_PAD = 16   # spazio fra il bordo del riquadro e il contenuto
TITLE_SPACE = 30  # altezza riservata al titolo del riquadro


# ── Disegno delle immagini ────────────────────────────────────────────────────

def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


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


def _glass(root, w, h, radius, top, bottom=None, border=None, border_alpha=1.0,
           border_width=1.0, highlight=0.0, shadow=0.0, margin=(0, 0, 0, 0), bg=BG,
           dot=None, shape_width=None):
    """Immagine w×h di una forma arrotondata fusa sullo sfondo bg.

    top/bottom: colori del riempimento (sfumato in verticale); highlight: forza
    del riflesso chiaro sul bordo superiore; shadow: opacità dell'ombra sotto;
    margin: spazio attorno alla forma; dot: (raggio, colore[, x[, ombra]]) pallino,
    al centro se x è None;
    shape_width: larghezza della forma se più stretta dell'immagine (a sinistra).
    """
    bg_c, top_c = _rgb(bg), _rgb(top)
    bottom_c = _rgb(bottom) if bottom else top_c
    border_c = _rgb(border) if border else None
    shadow_c = _rgb("#1e2a44")
    white = (255, 255, 255)
    ml, mt, mr, mb = margin
    x0, y0 = ml, mt
    x1 = ml + shape_width if shape_width else w - mr
    y1 = h - mb
    r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)

    rows = []
    for y in range(h):
        py = y + 0.5
        t = _clamp((py - y0) / max(y1 - y0, 1))
        fill = _mix(top_c, bottom_c, t)
        row = []
        for x in range(w):
            px = x + 0.5
            c = bg_c
            if shadow:
                # ombra spostata in basso e sfumata
                ds = _sdf(px, py - 2.5, x0, y0, x1, y1, r)
                c = _mix(c, shadow_c, shadow * _clamp(1 - (ds + 1) / 5) ** 2)
            d = _sdf(px, py, x0, y0, x1, y1, r)
            cover = _clamp(0.5 - d)
            if cover > 0:
                color = fill
                if highlight:
                    # riflesso: anello interno, solo nella parte alta
                    ring = _clamp(0.5 - (d + 1)) - _clamp(0.5 - (d + 2.5))
                    color = _mix(color, white, highlight * ring * _clamp(1 - t * 2.2))
                if dot:
                    dr, dc = dot[:2]
                    dx = dot[2] if len(dot) > 2 else (x0 + x1) / 2
                    halo = dot[3] if len(dot) > 3 else 0
                    dd = math.hypot(px - dx, py - (y0 + y1) / 2 - halo * 2) - dr
                    if halo:  # ombra morbida sotto il pallino
                        color = _mix(color, shadow_c, halo * _clamp(1 - (dd + 0.5) / 3) ** 2)
                    dd = math.hypot(px - dx, py - (y0 + y1) / 2) - dr
                    color = _mix(color, _rgb(dc), _clamp(0.5 - dd))
                if border_c:
                    ring = cover - _clamp(0.5 - (d + border_width))
                    color = _mix(color, border_c, border_alpha * _clamp(ring / cover))
                c = _mix(c, color, cover)
            row.append("#%02x%02x%02x" % tuple(int(round(v)) for v in c))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=root, width=w, height=h)
    image.put(" ".join(rows))
    root._glass_images.append(image)  # senza riferimento Tk perderebbe l'immagine
    return image


def _element(style, name, images, border, sticky="nsew"):
    """Elemento immagine; images = [(stati, immagine), ...], il primo è il normale.

    border: le parti dell'immagine che non vengono stirate (angoli e bordi); deve
    lasciare almeno una riga e una colonna centrali. padding 0: lo spazio attorno
    al contenuto lo decide il padding dello stile, non il bordo dell'immagine.
    """
    default = images[0][1]
    specs = [(*states, image) for states, image in images[1:]]
    style.element_create(name, "image", default, *specs, border=border, padding=0,
                         sticky=sticky)


# ── Tema ──────────────────────────────────────────────────────────────────────

def apply(root):
    families = set(tkfont.families(root))
    family = next((f for f in FONT_FAMILIES if f in families), "TkDefaultFont")
    title_family = next((f for f in TITLE_FAMILIES if f in families), family)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    base = (family, 10)
    semibold = (f"{family} Semibold" if f"{family} Semibold" in families else family, 10,
                "normal" if f"{family} Semibold" in families else "bold")
    root._glass_images = []

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
    root.option_add("*Button.background", FIELD)
    root.option_add("*Button.activeBackground", ACCENT_SOFT)
    root.option_add("*Button.borderWidth", 0)
    root.option_add("*Button.padX", 16)
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

    # riquadri: contenuto che galleggia sullo sfondo
    ml, mt, mr, mb = CARD_MARGIN
    card = _glass(root, 2 * CARD_RADIUS + ml + mr + 4, 2 * CARD_RADIUS + mt + mb + 4,
                  CARD_RADIUS, CARD, border="#d5dce7", highlight=0.9, shadow=0.10,
                  margin=CARD_MARGIN)
    _element(style, "glass.card", [((), card)],
             border=(CARD_RADIUS + ml, CARD_RADIUS + mt, CARD_RADIUS + mr, CARD_RADIUS + mb))
    style.layout("Card.TFrame", [("glass.card", {"sticky": "nswe"})])
    style.configure("Card.TFrame", background=CARD)

    style.configure("Divider.TFrame", background="#d9dfe9")

    # testi
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 9))
    style.configure("Status.TLabel", background=BG, foreground=MUTED)
    style.configure("Link.TLabel", background=BG, foreground=MUTED, font=(family, 9))
    style.configure("LinkHover.TLabel", background=BG, foreground=ACCENT,
                    font=(family, 9, "underline"))
    style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT,
                    font=(title_family, 11, "bold"))
    for name in ("TLabel", "Muted.TLabel"):
        style.configure(f"Card.{name}", background=CARD)
    style.configure("Card.Muted.TLabel", foreground=MUTED, font=(family, 9))
    style.configure("TLabelframe", background=BG)
    style.configure("TLabelframe.Label", background=BG, font=semibold)

    style.configure("Inner.TFrame", background=CARD)  # gruppo di widget dentro un riquadro

    # pulsanti a capsula di vetro chiaro: TButton nei riquadri, Page.TButton fuori
    m = (1, 1, 1, 2)
    for prefix, bg in (("", CARD), ("Page.", BG)):
        button = [
            ((), _glass(root, 44, 34, 14, "#ffffff", "#f1f4f9", border="#cfd7e3",
                        highlight=1.0, shadow=0.08, margin=m, bg=bg)),
            (("disabled",), _glass(root, 44, 34, 14, "#f0f2f6", border="#e1e6ed",
                                   margin=m, bg=bg)),
            (("pressed",), _glass(root, 44, 34, 14, "#e6ebf3", "#dfe6f0", border="#c3ccda",
                                  margin=m, bg=bg)),
            (("active",), _glass(root, 44, 34, 14, "#ffffff", "#e8f1ff", border="#a9c6ee",
                                 highlight=1.0, shadow=0.10, margin=m, bg=bg)),
        ]
        element = f"glass.{prefix}button"
        _element(style, element, button, border=(15, 15, 15, 16))
        style.layout(f"{prefix}TButton", [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        style.configure(f"{prefix}TButton", background=bg, foreground=TEXT, padding=(16, 7),
                        anchor="center", font=base)
        style.map(f"{prefix}TButton", foreground=[("disabled", DISABLED_TEXT)])

    # pulsante principale: vetro colorato, sullo sfondo della finestra. Primary è
    # quello grande in fondo alla finestra, Accent ha l'altezza dei pulsanti normali
    m = (1, 1, 1, 3)
    for name, h, r, border, padding, button_font in (
            ("Primary", 44, 16, (17, 17, 17, 19), (24, 11), (title_family, 11, "bold")),
            ("Accent", 34, 14, (15, 15, 15, 17), (18, 7), semibold)):
        images = [
            ((), _glass(root, 52, h, r, "#3e9dff", "#0a76f0", border="#0767d6",
                        highlight=0.55, shadow=0.18, margin=m)),
            (("disabled",), _glass(root, 52, h, r, "#e2e6ed", border="#d6dce5", margin=m)),
            (("pressed",), _glass(root, 52, h, r, "#0a6fe0", "#0861c7", border="#0558b8",
                                  highlight=0.25, margin=m)),
            (("active",), _glass(root, 52, h, r, "#5aaeff", "#1a84ff", border="#0a72e8",
                                 highlight=0.65, shadow=0.22, margin=m)),
        ]
        element = f"glass.{name.lower()}"
        _element(style, element, images, border=border)
        style.layout(f"{name}.TButton", [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        style.configure(f"{name}.TButton", foreground="#ffffff", padding=padding,
                        font=button_font, anchor="center")
        style.map(f"{name}.TButton", foreground=[("disabled", DISABLED_TEXT)])

    # campi: bianchi, angoli concentrici con i riquadri, anello blu col fuoco
    field_images = {}
    for key, bg in (("card", CARD), ("page", BG)):
        field_images[key] = [
            ((), _glass(root, 28, 32, 10, FIELD, border="#cdd5e1", bg=bg)),
            (("disabled",), _glass(root, 28, 32, 10, "#f3f5f8", border="#e0e5ec", bg=bg)),
            (("focus",), _glass(root, 28, 32, 10, FIELD, border=ACCENT, border_width=2, bg=bg)),
        ]
    _element(style, "glass.field", field_images["card"], border=11)
    _element(style, "glass.pagefield", field_images["page"], border=11)
    for prefix, element in (("", "glass.field"), ("Page.", "glass.pagefield")):
        style.layout(f"{prefix}TEntry", [(element, {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})])
        # la freccia sta dentro il padding, così non copre l'angolo arrotondato
        style.layout(f"{prefix}TCombobox", [(element, {"sticky": "nswe", "children": [
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])
        for name in ("TEntry", "TCombobox"):
            style.configure(f"{prefix}{name}", fieldbackground=FIELD, background=FIELD,
                            foreground=TEXT, bordercolor=FIELD, lightcolor=FIELD,
                            darkcolor=FIELD, padding=(10, 6, 8, 6), arrowcolor=MUTED,
                            arrowsize=14)
            style.map(f"{prefix}{name}",
                      fieldbackground=[("disabled", "#f3f5f8")],
                      background=[("disabled", "#f3f5f8")],
                      bordercolor=[("disabled", "#f3f5f8")],
                      lightcolor=[("disabled", "#f3f5f8")],
                      darkcolor=[("disabled", "#f3f5f8")],
                      arrowcolor=[("disabled", DISABLED_TEXT), ("active", ACCENT)],
                      selectbackground=[("readonly", FIELD)],
                      selectforeground=[("readonly", TEXT)])
    # il riquadro con il campo: padding interno per gli elenchi tk (field_box)
    style.layout("Field.TFrame", [("glass.field", {"sticky": "nswe"})])

    # scelte: indicatore rotondo, pieno di blu quando è selezionato
    radio = [
        ((), _glass(root, 26, 20, 9, FIELD, border="#b9c3d1", shape_width=18,
                    margin=(0, 1, 0, 1), bg=CARD)),
        (("disabled", "selected"), _glass(root, 26, 20, 9, "#c9d1dc", shape_width=18,
                                          margin=(0, 1, 0, 1), bg=CARD, dot=(3.2, "#f3f5f8"))),
        (("disabled",), _glass(root, 26, 20, 9, "#f3f5f8", border="#dde2e9", shape_width=18,
                               margin=(0, 1, 0, 1), bg=CARD)),
        (("selected",), _glass(root, 26, 20, 9, "#3e9dff", "#0a76f0", border="#0767d6",
                               highlight=0.5, shape_width=18, margin=(0, 1, 0, 1), bg=CARD,
                               dot=(3.2, "#ffffff"))),
        (("active",), _glass(root, 26, 20, 9, FIELD, border=ACCENT, shape_width=18,
                             margin=(0, 1, 0, 1), bg=CARD)),
    ]
    _element(style, "glass.radio", radio, border=0, sticky="")
    for prefix, bg in (("", BG), ("Card.", CARD)):
        style.layout(f"{prefix}TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [
            ("glass.radio", {"side": "left", "sticky": ""}),
            ("Radiobutton.label", {"side": "left", "sticky": "nswe"})]})])
        style.configure(f"{prefix}TRadiobutton", background=bg, padding=(0, 3))
        style.map(f"{prefix}TRadiobutton", background=[("active", bg)])

    # interruttore: capsula con il pomello bianco, blu quando è acceso
    m = (1, 1, 1, 1)
    switch = [
        ((), _glass(root, 42, 24, 11, "#d9dee6", "#e3e7ee", border="#c8d0dc",
                    margin=m, bg=CARD, dot=(9, "#ffffff", 12, 0.35))),
        (("disabled", "selected"), _glass(root, 42, 24, 11, "#b9d6fb", margin=m, bg=CARD,
                                          dot=(9, "#f6f8fb", 30))),
        (("disabled",), _glass(root, 42, 24, 11, "#eceff3", border="#e0e5ec", margin=m,
                               bg=CARD, dot=(9, "#f6f8fb", 12))),
        (("selected",), _glass(root, 42, 24, 11, "#3e9dff", "#0a76f0", border="#0767d6",
                               highlight=0.5, margin=m, bg=CARD,
                               dot=(9, "#ffffff", 30, 0.35))),
    ]
    _element(style, "glass.switch", switch, border=0, sticky="")
    style.layout("Switch.TCheckbutton", [("glass.switch", {"sticky": ""})])
    style.configure("Switch.TCheckbutton", background=CARD, padding=0)
    style.map("Switch.TCheckbutton", background=[("active", CARD)])

    # schede: controllo segmentato, pillola di vetro sulla scheda scelta
    track = _glass(root, 48, 44, 20, TRACK, "#e6e9f0", border="#d3d9e3")
    _element(style, "glass.track", [((), track)], border=20)
    style.layout("Segments.TFrame", [("glass.track", {"sticky": "nswe"})])
    style.configure("Segments.TFrame", background=TRACK)
    m = (1, 1, 1, 2)
    segment = [
        ((), _glass(root, 40, 34, 15, TRACK, bg=TRACK, margin=m)),
        (("selected",), _glass(root, 40, 34, 15, "#ffffff", "#f7f9fc", border="#d0d7e2",
                               highlight=1.0, shadow=0.12, margin=m, bg=TRACK)),
        (("active",), _glass(root, 40, 34, 15, "#edf0f5", bg=TRACK, margin=m)),
    ]
    _element(style, "glass.segment", segment, border=(16, 16, 16, 17))
    style.layout("Segment.TRadiobutton", [("glass.segment", {"sticky": "nswe", "children": [
        ("Toolbutton.padding", {"sticky": "nswe", "children": [
            ("Toolbutton.label", {"sticky": "nswe"})]})]})])
    style.configure("Segment.TRadiobutton", background=TRACK, foreground=MUTED,
                    padding=(22, 8), anchor="center", font=semibold)
    style.map("Segment.TRadiobutton", background=[("active", TRACK)],
              foreground=[("selected", TEXT), ("active", TEXT)])

    # avanzamento: capsula sottile
    trough = _glass(root, 16, 8, 4, "#dde3ec")
    pbar = _glass(root, 16, 8, 4, "#3e9dff", "#0a76f0", highlight=0.4)
    _element(style, "glass.Horizontal.Progressbar.trough", [((), trough)], border=4)
    _element(style, "glass.Horizontal.Progressbar.pbar", [((), pbar)], border=4)
    style.layout("Horizontal.TProgressbar", [("glass.Horizontal.Progressbar.trough", {
        "sticky": "nswe", "children": [
            ("glass.Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])
    style.configure("Horizontal.TProgressbar", thickness=8)

    # barre di scorrimento: solo il cursore a capsula, senza frecce
    for prefix, bg, thumb, hover in (("", FIELD, "#c4ccd8", "#a3aebd"),
                                     ("Page.", BG, "#c4ccd8", "#a3aebd"),
                                     ("Dark.", LOG_BG, "#3a4456", "#556075")):
        images = [((), _glass(root, 12, 28, 4, thumb, margin=(3, 2, 3, 2), bg=bg)),
                  (("pressed",), _glass(root, 12, 28, 4, hover, margin=(3, 2, 3, 2), bg=bg)),
                  (("active",), _glass(root, 12, 28, 4, hover, margin=(3, 2, 3, 2), bg=bg))]
        _element(style, f"glass.{prefix}Vertical.Scrollbar.thumb", images, border=(6, 7))
        style.layout(f"{prefix}Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "sticky": "ns", "children": [
                (f"glass.{prefix}Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(f"{prefix}Vertical.TScrollbar", troughcolor=bg, background=bg,
                        bordercolor=bg, lightcolor=bg, darkcolor=bg, width=12)

    # tabelle
    style.layout("Treeview", [("glass.field", {"sticky": "nswe", "children": [
        ("Treeview.padding", {"sticky": "nswe", "children": [
            ("Treeview.treearea", {"sticky": "nswe"})]})]})])
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    rowheight=28, padding=6)
    style.map("Treeview", background=[("selected", ACCENT_SOFT)],
              foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, font=semibold,
                    borderwidth=0, relief="flat", padding=(6, 4),
                    bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD)
    style.map("Treeview.Heading", background=[("active", "#f3f6fa")])

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
    """Riquadro arrotondato con ombra, con il titolo in alto a sinistra.

    Il titolo è posizionato con place, così dentro il riquadro si possono usare
    sia grid sia pack; il padding superiore gli lascia spazio. Le coordinate di
    place partono dall'interno del padding, per questo sono negative.
    """
    ml, mt, mr, mb = CARD_MARGIN
    top = CARD_PAD + mt + (TITLE_SPACE if title else 0)
    frame = ttk.Frame(parent, style="Card.TFrame",
                      padding=(CARD_PAD + ml, top, CARD_PAD + mr, CARD_PAD + mb))
    if title:
        frame.title_y = -(top - mt - CARD_PAD + 4)
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
    """Schede scelte con un controllo segmentato a capsula, centrato in alto.

    Le pagine stanno tutte nella stessa cella della griglia, una sopra l'altra:
    la scheda scelta passa in primo piano. Così l'area è alta quanto la pagina
    più alta e la finestra non cambia misura passando da una scheda all'altra.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.segments = ttk.Frame(self, style="Segments.TFrame", padding=3)
        self.segments.grid(row=0, column=0, pady=(14, 0))
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
        ttk.Radiobutton(self.segments, text=name, value=name, variable=self.current,
                        style="Segment.TRadiobutton", takefocus=False,
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
        root._log_panel = _glass(root, 44, 46, 16, LOG_BG, "#121722", border="#0b0f17",
                                 highlight=0.12, shadow=0.16, margin=CARD_MARGIN)
        ml, mt, mr, mb = CARD_MARGIN
        style = ttk.Style(root)
        _element(style, "glass.log", [((), root._log_panel)],
                 border=(16 + ml, 16 + mt, 16 + mr, 16 + mb))
        style.layout("Log.TFrame", [("glass.log", {"sticky": "nswe"})])
        style.configure("Log.TFrame", background=LOG_BG)
    ml, mt, mr, mb = CARD_MARGIN
    box = ttk.Frame(parent, style="Log.TFrame", padding=(8 + ml, 8 + mt, 6 + mr, 8 + mb))
    text = tk.Text(box, height=height, state="disabled", wrap="word", relief="flat",
                   borderwidth=0, highlightthickness=0, padx=8, pady=4,
                   background=LOG_BG, foreground=LOG_TEXT, insertbackground=LOG_TEXT,
                   selectbackground="#334155", font=(MONO_FAMILY, 9))
    scroll = ttk.Scrollbar(box, orient="vertical", command=text.yview,
                           style="Dark.Vertical.TScrollbar")
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return box, text


# ── Posizione della finestra ──────────────────────────────────────────────────

def work_area(root, at=None):
    """(x, y, larghezza, altezza) dell'area utile del monitor che contiene il punto
    at (x, y), o di quello su cui c'è il mouse.

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
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        point = wintypes.POINT(*at) if at else wintypes.POINT()
        if not at:
            user32.GetCursorPos(ctypes.byref(point))
        monitor = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
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

        frame = ttk.Frame(self, padding=(24, 20, 24, 18))
        frame.pack(fill="both", expand=True)
        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        focus = self.body(body)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(20, 0))
        default = buttons[-1][1]
        for i, (text, value) in enumerate(reversed(buttons)):
            ttk.Button(row, text=text, style="Accent.TButton" if i == 0 else "Page.TButton",
                       command=lambda v=value: self.done(v)).pack(side="right", padx=(8, 0))
        self.bind("<Return>", lambda _e: self.done(default))
        self.bind("<Escape>", lambda _e: self.done(cancel))
        self.protocol("WM_DELETE_WINDOW", lambda: self.done(cancel))

        place_over(self, parent)
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


ICONS = {  # simbolo, colore in alto e in basso del cerchio
    "info": ("i", "#3e9dff", "#0a76f0"),
    "question": ("?", "#3e9dff", "#0a76f0"),
    "warning": ("!", "#ffb340", "#f08a00"),
    "error": ("✕", "#ff6259", "#e0352b"),
}


class _Message(Dialog):
    def __init__(self, parent, title, message, icon, buttons, cancel):
        self.message, self.icon = message, icon
        super().__init__(parent, title, buttons, cancel)

    def body(self, master):
        root = self._root()
        cache = root.__dict__.setdefault("_glass_icons", {})
        symbol, top, bottom = ICONS[self.icon]
        if self.icon not in cache:
            cache[self.icon] = _glass(root, 36, 36, 18, top, bottom, highlight=0.5)
        ttk.Label(master, image=cache[self.icon], text=symbol, compound="center",
                  foreground="#ffffff", font=(tkfont.nametofont("TkDefaultFont").actual("family"),
                                              14, "bold")).pack(side="left", anchor="n")
        ttk.Label(master, text=self.message, wraplength=420, justify="left").pack(
            side="left", anchor="n", padx=(16, 0), pady=(6, 0))
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
