import customtkinter as ctk
from src.core.config import WIN11, FONT_FAMILY

def make_card(parent, **kw) -> ctk.CTkFrame:
    defaults = dict(
        corner_radius=10,
        fg_color=WIN11["bg_surface"],
        border_width=1,
        border_color=WIN11["border"],
    )
    defaults.update(kw)
    return ctk.CTkFrame(parent, **defaults)

def make_section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=(FONT_FAMILY, 11),
        text_color=WIN11["text_secondary"],
    )

def make_heading(parent, text: str, size: int = 14) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=(FONT_FAMILY, size, "bold"),
        text_color=WIN11["text_primary"],
    )

def make_button(parent, text: str, command=None, style="accent", width=120, height=34, **kw) -> ctk.CTkButton:
    styles = {
        "accent":  dict(fg_color=WIN11["accent"],  hover_color=WIN11["accent_hover"],  text_color=WIN11["text_primary"]),
        "neutral": dict(fg_color=WIN11["bg_input"], hover_color=WIN11["bg_hover"],     text_color=WIN11["text_primary"],
                        border_width=1, border_color=WIN11["border"]),
        "danger":  dict(fg_color=WIN11["danger"],   hover_color=WIN11["danger_hover"],  text_color=WIN11["text_primary"]),
        "success": dict(fg_color=WIN11["success"],  hover_color=WIN11["success_hover"], text_color=WIN11["text_primary"]),
        "ghost":   dict(fg_color="transparent",     hover_color=WIN11["bg_hover"],      text_color=WIN11["text_primary"],
                        border_width=1, border_color=WIN11["border"]),
    }
    cfg = styles.get(style, styles["accent"])
    cfg.update(kw)
    return ctk.CTkButton(
        parent, text=text, command=command,
        width=width, height=height,
        corner_radius=6,
        font=(FONT_FAMILY, 12),
        **cfg,
    )

def make_entry(parent, placeholder: str = "", width: int = 240, show: str = "") -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent,
        placeholder_text=placeholder,
        width=width,
        height=36,
        corner_radius=6,
        fg_color=WIN11["bg_input"],
        border_color=WIN11["border"],
        border_width=1,
        text_color=WIN11["text_primary"],
        placeholder_text_color=WIN11["text_disabled"],
        font=(FONT_FAMILY, 12),
        show=show,
    )
