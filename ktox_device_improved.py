# VIEW MODE IMPROVEMENTS FOR ktox_device.py
# This file contains the improved view mode rendering functions

# ════════════════════════════════════════════════════════════════════════════════
# IMPROVED VIEW MODES - Drop-in replacements for existing GetMenu* functions
# ════════════════════════════════════════════════════════════════════════════════

def GetMenuGrid(inlist, duplicates=False):
    """Improved Grid: 2x3 grid with proper spacing, icons contained, text labels below."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    COLS = 2
    ROWS = 3
    ITEMS_PER_VIEW = COLS * ROWS
    CELL_W = 58
    CELL_H = 36
    GAP = 2
    START_X = 4
    START_Y = 16

    while True:
        offset = (index // ITEMS_PER_VIEW) * ITEMS_PER_VIEW

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            for i, raw in enumerate(inlist[offset:offset+ITEMS_PER_VIEW]):
                if offset + i >= total:
                    break
                txt = raw if not duplicates else raw.split("#", 1)[1]
                row = i // COLS
                col = i % COLS
                x = START_X + col * (CELL_W + GAP)
                y = START_Y + row * (CELL_H + GAP)
                sel = (offset + i == index)

                if sel:
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H],
                                 fill=color.select, outline=color.border, width=2)
                else:
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H],
                                 outline=color.border, width=1)

                fill = color.selected_text if sel else color.text
                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    # Icon centered in top half
                    draw.text((x + CELL_W // 2, y + 10), icon, font=medium_icon_font, fill=fill, anchor="mm")
                    # Text label centered in bottom half
                    t = _truncate(txt.strip(), 14)
                    draw.text((x + CELL_W // 2, y + 28), t, font=small_font, fill=fill, anchor="mm")
                else:
                    t = _truncate(txt.strip(), 16)
                    draw.text((x + CELL_W // 2, y + 18), t, font=text_font, fill=fill, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + COLS, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - COLS, 0)
        elif btn == "KEY_RIGHT_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_LEFT_PIN":
            index = max(index - 1, 0) if index % COLS != 0 else index
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuCarousel(inlist, duplicates=False):
    """Improved Carousel: HUGE icon fills box, page indicator moved to bottom corner."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 20, 124, 115], outline=color.border, width=1)

            raw = inlist[index]
            txt = raw if not duplicates else raw.split("#", 1)[1]

            icon = _icon_for(txt)
            if icon and _ui_ux.get("show_icons", True):
                # HUGE icon takes up most of the box
                draw.text((64, 60), icon, font=large_icon_font, fill=color.selected_text, anchor="mm")
                display_txt = _truncate(txt.strip(), 60)
                draw.text((64, 108), display_txt, font=small_font, fill=color.text, anchor="mm")
            else:
                display_txt = _truncate(txt.strip(), 100)
                draw.text((64, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

            # Page number in bottom right corner
            if total > 1:
                page_txt = f"{index+1}/{total}"
                draw.text((118, 116), page_txt, font=small_font, fill=color.text, anchor="rb")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_LEFT_PIN":
            index = (index - 1) % total
        elif btn == "KEY_RIGHT_PIN":
            index = (index + 1) % total
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuPanel(inlist, duplicates=False):
    """Improved Panel: narrow left sidebar with small icons, large right panel with BIG centered icon."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    SIDEBAR_ITEMS = 5
    ICON_H = 20

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            # Narrow left sidebar with small icons
            draw.rectangle([3, 14, 27, 127], fill=color.panel_bg, outline=color.border, width=1)

            offset = max(0, min(index - SIDEBAR_ITEMS // 2, total - SIDEBAR_ITEMS))
            for i in range(SIDEBAR_ITEMS):
                item_idx = offset + i
                if item_idx >= total:
                    break
                label = inlist[item_idx] if not duplicates else inlist[item_idx].split("#", 1)[1]
                y = 18 + i * ICON_H
                fill = color.selected_text if item_idx == index else color.text

                icon = _icon_for(label)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((15, y + 8), icon, font=icon_font, fill=fill, anchor="mm")

            if total > 0:
                raw = inlist[index]
                txt = raw if not duplicates else raw.split("#", 1)[1]
                # Large content panel on right
                draw.rectangle([29, 15, 125, 125], outline=color.border, width=2, fill=color.background)

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    # HUGE icon, properly centered
                    draw.text((77, 55), icon, font=large_icon_font, fill=color.selected_text, anchor="mm")
                    display_txt = _truncate(txt.strip(), 40)
                    draw.text((77, 103), display_txt, font=text_font, fill=color.selected_text, anchor="mm")
                else:
                    display_txt = _truncate(txt.strip(), 50)
                    draw.text((77, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN", "KEY_LEFT_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuTable(inlist, duplicates=False):
    """Improved Table: full-width rows with icon + text, clean layout."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    ROWS = 6
    ROW_H = 16
    START_Y = 16

    while True:
        offset = max(0, min(index - 2, total - ROWS))

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            for i in range(ROWS):
                item_idx = offset + i
                if item_idx >= total:
                    break
                raw = inlist[item_idx]
                txt = raw if not duplicates else raw.split("#", 1)[1]
                y = START_Y + i * ROW_H
                sel = (item_idx == index)

                if sel:
                    draw.rectangle([3, y, 124, y + ROW_H - 1], fill=color.select)
                    fill = color.selected_text
                else:
                    fill = color.text

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((7, y + 7), icon, font=icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip(), 60)
                    draw.text((22, y + 1), t, font=text_font, fill=fill)
                else:
                    t = _truncate(txt.strip(), 75)
                    draw.text((7, y + 1), t, font=text_font, fill=fill)

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - 1, 0)
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN", "KEY_LEFT_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuPaged(inlist, duplicates=False):
    """Improved Paged: 3 items per page, BIGGER icons and text, properly centered."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    ITEMS_PER_PAGE = 3
    ITEM_H = 35
    START_Y = 25

    while True:
        page = index // ITEMS_PER_PAGE
        page_items = inlist[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
            page_text = f"Page {page + 1}/{(total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE}"
            _centered(page_text, 13, font=small_font, fill=color.border)
            draw.line([(3, 24), (125, 24)], fill=color.border, width=1)

            for i, raw in enumerate(page_items):
                txt = raw if not duplicates else raw.split("#", 1)[1]
                y = START_Y + i * ITEM_H
                sel = (page * ITEMS_PER_PAGE + i == index)

                if sel:
                    draw.rectangle([3, y, 125, y + ITEM_H - 2], fill=color.select, outline=color.border, width=1)
                    fill = color.selected_text
                else:
                    draw.rectangle([3, y, 125, y + ITEM_H - 2], outline=color.border, width=1)
                    fill = color.text

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((18, y + 17), icon, font=medium_icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip(), 50)
                    draw.text((35, y + 17), t, font=text_font, fill=fill, anchor="lm")
                else:
                    t = _truncate(txt.strip(), 70)
                    draw.text((64, y + 17), t, font=text_font, fill=fill, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - 1, 0)
        elif btn == "KEY_RIGHT_PIN":
            if (index + 1) % ITEMS_PER_PAGE != 0 and index + 1 < total:
                index += 1
        elif btn == "KEY_LEFT_PIN":
            if index % ITEMS_PER_PAGE != 0:
                index -= 1
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuThumbnail(inlist, duplicates=False):
    """Improved Thumbnail: 2x2 grid with large icons contained, text labels below."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    COLS = 2
    ROWS = 2
    ITEMS_PER_VIEW = COLS * ROWS
    CELL_W = 60
    CELL_H = 50
    START_X = 4
    START_Y = 18

    while True:
        offset = (index // ITEMS_PER_VIEW) * ITEMS_PER_VIEW

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            for i, raw in enumerate(inlist[offset:offset+ITEMS_PER_VIEW]):
                if offset + i >= total:
                    break
                txt = raw if not duplicates else raw.split("#", 1)[1]
                row = i // COLS
                col = i % COLS
                x = START_X + col * CELL_W
                y = START_Y + row * CELL_H
                sel = (offset + i == index)

                if sel:
                    draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                                 fill=color.select, outline=color.border, width=2)
                    icon_fill = color.selected_text
                    text_fill = color.selected_text
                else:
                    draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                                 outline=color.border, width=1)
                    icon_fill = color.text
                    text_fill = color.text

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    # Large icon centered in top portion
                    draw.text((x + 30, y + 12), icon, font=medium_icon_font, fill=icon_fill, anchor="mm")
                    # Text label centered in bottom
                    label = _truncate(txt.strip(), 14)
                    draw.text((x + 30, y + 39), label, font=small_font, fill=text_fill, anchor="mm")
                else:
                    label = _truncate(txt.strip(), 16)
                    draw.text((x + 30, y + 25), label, font=text_font, fill=text_fill, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + COLS, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - COLS, 0)
        elif btn == "KEY_RIGHT_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_LEFT_PIN":
            index = max(index - 1, 0) if index % COLS != 0 else index
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuVerticalCarousel(inlist, duplicates=False):
    """Improved V-Carousel: HUGE centered icon, page indicator in footer."""
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 20, 124, 115], outline=color.border, width=1)

            raw = inlist[index]
            txt = raw if not duplicates else raw.split("#", 1)[1]

            icon = _icon_for(txt)
            if icon and _ui_ux.get("show_icons", True):
                # HUGE icon in center
                draw.text((64, 60), icon, font=large_icon_font, fill=color.selected_text, anchor="mm")
                display_txt = _truncate(txt.strip(), 60)
                draw.text((64, 105), display_txt, font=small_font, fill=color.text, anchor="mm")
            else:
                display_txt = _truncate(txt.strip(), 100)
                draw.text((64, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

            # Page indicator in footer
            if total > 1:
                page_txt = f"{index+1}/{total}"
                draw.text((64, 116), page_txt, font=small_font, fill=color.text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_LEFT_PIN":
            index = (index - 1) % total
        elif btn == "KEY_RIGHT_PIN":
            index = (index + 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""
