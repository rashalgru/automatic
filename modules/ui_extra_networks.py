import json
import html
import os.path
import urllib.parse
from pathlib import Path
import gradio as gr
from modules import shared, scripts
from modules.generation_parameters_copypaste import image_from_url_text
from modules.ui_components import ToolButton

extra_pages = []
allowed_dirs = set()

refresh_symbol = '\U0001f504'  # 🔄
close_symbol = '\U0000274C'  # ❌

def register_page(page):
    """registers extra networks page for the UI; recommend doing it in on_before_ui() callback for extensions"""
    extra_pages.append(page)
    allowed_dirs.clear()
    allowed_dirs.update(set(sum([x.allowed_directories_for_previews() for x in extra_pages], [])))


def fetch_file(filename: str = ""):
    from starlette.responses import FileResponse, JSONResponse
    if not any(Path(x).absolute() in Path(filename).absolute().parents for x in allowed_dirs):
        return JSONResponse({"error": f"File cannot be fetched: {filename}. Must be in one of directories registered by extra pages."})
    if os.path.splitext(filename)[1].lower() not in (".png", ".jpg", ".webp"):
        return JSONResponse({"error": f"File cannot be fetched: {filename}. Only png and jpg and webp."})
    return FileResponse(filename, headers={"Accept-Ranges": "bytes"})


def get_metadata(page: str = "", item: str = ""):
    from starlette.responses import JSONResponse
    page = next(iter([x for x in extra_pages if x.name == page]), None)
    if page is None:
        return JSONResponse({})
    metadata = page.metadata.get(item)
    if metadata is None:
        return JSONResponse({})
    return JSONResponse({"metadata": metadata})


def add_pages_to_demo(app):
    app.add_api_route("/sd_extra_networks/thumb", fetch_file, methods=["GET"])
    app.add_api_route("/sd_extra_networks/metadata", get_metadata, methods=["GET"])


class ExtraNetworksPage:
    def __init__(self, title):
        self.title = title
        self.name = title.lower()
        self.card_long = shared.html("extra-networks-card-long.html")
        self.card_short = shared.html("extra-networks-card-short.html")
        self.allow_negative_prompt = False
        self.metadata = {}
        self.items = []

    def refresh(self):
        pass

    def create_xyz_grid(self):
        xyz_grid = [x for x in scripts.scripts_data if x.script_class.__module__ == "xyz_grid.py"][0].module

        def add_prompt(p, opt, x):
            for item in [x for x in self.items if x["name"] == opt]:
                try:
                    p.prompt = f'{p.prompt} {eval(item["prompt"])}' # pylint: disable=eval-used
                except Exception as e:
                    shared.log.error(f'Cannot evaluate extra network prompt: {item["prompt"]} {e}')

        if not any(self.title in x.label for x in xyz_grid.axis_options):
            if self.title == 'Checkpoints':
                return
            opt = xyz_grid.AxisOption(f"[Network] {self.title}", str, add_prompt, choices=lambda: [x["name"] for x in self.items])
            xyz_grid.axis_options.append(opt)

    def link_preview(self, filename):
        quoted_filename = urllib.parse.quote(filename.replace('\\', '/'))
        mtime = os.path.getmtime(filename)
        return f"./sd_extra_networks/thumb?filename={quoted_filename}&mtime={mtime}"

    def search_terms_from_path(self, filename, possible_directories=None):
        abspath = os.path.abspath(filename)
        for parentdir in (possible_directories if possible_directories is not None else self.allowed_directories_for_previews()):
            parentdir = os.path.abspath(parentdir)
            if abspath.startswith(parentdir):
                return abspath[len(parentdir):].replace('\\', '/')
        return ""

    def create_html(self, tabname):
        view = shared.opts.extra_networks_default_view
        items_html = ''
        self.metadata = {}
        subdirs = {}
        allowed_folders = [os.path.abspath(x) for x in self.allowed_directories_for_previews()]
        for parentdir in [*set(allowed_folders)]:
            for root, dirs, _files in os.walk(parentdir, followlinks=True):
                for dirname in dirs:
                    x = os.path.join(root, dirname)
                    if not os.path.isdir(x):
                        continue
                    subdir = os.path.abspath(x)[len(parentdir):].replace("\\", "/")
                    while subdir.startswith("/"):
                        subdir = subdir[1:]
                    is_empty = len(os.listdir(x)) == 0
                    if not is_empty and not subdir.endswith("/"):
                        subdir = subdir + "/"
                    subdirs[subdir] = 1
        if subdirs:
            subdirs = {"": 1, **subdirs}
        subdirs_html = "".join([f"""
            <button class='lg secondary gradio-button custom-button{" search-all" if subdir=="" else ""}' onclick='extraNetworksSearchButton("{tabname}_extra_tabs", event)'>
                {html.escape(subdir if subdir!="" else "all")}
            </button>""" for subdir in subdirs])
        try:
            self.items = list(self.list_items())
            self.create_xyz_grid()
            for item in self.items:
                metadata = item.get("metadata")
                if metadata:
                    self.metadata[item["name"]] = metadata
                items_html += self.create_html_for_item(item, tabname)
            if items_html == '':
                dirs = "".join([f"<li>{x}</li>" for x in self.allowed_directories_for_previews()])
                items_html = shared.html("extra-networks-no-cards.html").format(dirs=dirs)
            self_name_id = self.name.replace(" ", "_")
            res = f"""
                <div id='{tabname}_{self_name_id}_subdirs' class='extra-network-subdirs extra-network-subdirs-{view}'>
                    {subdirs_html}
                </div>
                <div id='{tabname}_{self_name_id}_cards' class='extra-network-{view}'>
                    {items_html}
                </div>
                """
            return res
        except Exception as e:
            shared.log.error(f'Extra networks page error: {e}')
            return ''

    def list_items(self):
        raise NotImplementedError()

    def allowed_directories_for_previews(self):
        return []

    def create_html_for_item(self, item, tabname):
        preview = item.get("preview", None)
        onclick = item.get("onclick", None)
        if onclick is None:
            onclick = '"' + html.escape(f"""return cardClicked({json.dumps(tabname)}, {item["prompt"]}, {"true" if self.allow_negative_prompt else "false"})""") + '"'
        height = f"height: {shared.opts.extra_networks_card_height}px;" if shared.opts.extra_networks_card_height else ''
        width = f"width: {shared.opts.extra_networks_card_width}px;" if shared.opts.extra_networks_card_width else ''
        background_image = f"background-image: url(\"{html.escape(preview)}\");" if preview else ''
        args = {
            "style": f"'{height}{width}{background_image}'",
            "prompt": item.get("prompt", None),
            "tabname": json.dumps(tabname),
            "local_preview": json.dumps(item["local_preview"]),
            "name": item["name"],
            "description": (item.get("description") or ""),
            "card_clicked": onclick,
            "save_card_description": '"' + html.escape(f"""return saveCardDescription(event, {json.dumps(tabname)}, {json.dumps(item["local_preview"])})""") + '"',
            "save_card_preview": '"' + html.escape(f"""return saveCardPreview(event, {json.dumps(tabname)}, {json.dumps(item["local_preview"])})""") + '"',
            "read_card_description": '"' + html.escape(f"""return readCardDescription(event, {json.dumps(tabname)}, {json.dumps(item["local_preview"])}, {json.dumps(item.get("description", ""))}, {json.dumps(self.name)}, {json.dumps(item["name"])})""") + '"',
            "search_term": item.get("search_term", ""),
            "read_card_metadata": '"' + html.escape(f"""return readCardMetadata(event, {json.dumps(self.name)}, {json.dumps(item["name"])})""") + '"',
        }
        if item.get("metadata"):
            return self.card_long.format(**args)
        else:
            return self.card_short.format(**args)

    def find_preview(self, path):
        """
        Find a preview PNG for a given path (without extension) and call link_preview on it.
        """
        preview_extensions = ["jpg", "jpeg", "png", "webp", "tiff", "jp2"]
        potential_files = sum([[path + "." + ext, path + ".preview." + ext] for ext in preview_extensions], [])
        for file in potential_files:
            if os.path.isfile(file):
                return self.link_preview(file)
        return None

    def find_description(self, path):
        """
        Find and read a description file for a given path (without extension).
        """
        for file in [f"{path}.txt", f"{path}.description.txt"]:
            try:
                with open(file, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                pass
        return None


def initialize():
    extra_pages.clear()


def register_default_pages():
    from modules.ui_extra_networks_textual_inversion import ExtraNetworksPageTextualInversion
    from modules.ui_extra_networks_hypernets import ExtraNetworksPageHypernetworks
    from modules.ui_extra_networks_checkpoints import ExtraNetworksPageCheckpoints
    register_page(ExtraNetworksPageTextualInversion())
    register_page(ExtraNetworksPageHypernetworks())
    register_page(ExtraNetworksPageCheckpoints())


class ExtraNetworksUi:
    def __init__(self):
        self.pages = None
        self.stored_extra_pages = []
        self.button_save_preview = None
        self.preview_target_filename = None
        self.button_save_description = None
        self.button_read_description = None
        self.description_target_filename = None
        self.description_input = None
        self.tabname = None
        self.search = None


def pages_in_preferred_order(pages):
    tab_order = [x.lower().strip() for x in shared.opts.ui_extra_networks_tab_reorder.split(",")]
    def tab_name_score(name):
        name = name.lower()
        for i, possible_match in enumerate(tab_order):
            if possible_match in name:
                return i
        return len(pages)
    tab_scores = {page.name: (tab_name_score(page.name), original_index) for original_index, page in enumerate(pages)}
    return sorted(pages, key=lambda x: tab_scores[x.name])


def create_ui(container, button, tabname):
    ui = ExtraNetworksUi()
    ui.pages = []
    ui.stored_extra_pages = pages_in_preferred_order(extra_pages.copy())
    ui.tabname = tabname
    with gr.Tabs(elem_id=tabname+"_extra_tabs"):
        ui.search = gr.Textbox('', show_label=False, elem_id=tabname+"_extra_search", placeholder="Search...", visible=True)
        ui.description_input = gr.TextArea('', show_label=False, elem_id=tabname+"_description_input", placeholder="Save/Replace Extra Network Description...", lines=2)
        button_refresh = ToolButton(refresh_symbol, elem_id=tabname+"_extra_refresh")
        button_close = ToolButton(close_symbol, elem_id=tabname+"_extra_close")
        ui.button_save_preview = gr.Button('Save preview', elem_id=tabname+"_save_preview", visible=False)
        ui.preview_target_filename = gr.Textbox('Preview save filename', elem_id=tabname+"_preview_filename", visible=False)
        ui.button_save_description = gr.Button('Save description', elem_id=tabname+"_save_description", visible=False)
        ui.button_read_description = gr.Button('Read description', elem_id=tabname+"_read_description", visible=False)
        ui.description_target_filename = gr.Textbox('Description save filename', elem_id=tabname+"_description_filename", visible=False)
        for page in ui.stored_extra_pages:
            with gr.Tab(page.title, id=page.title.lower().replace(" ", "_")):
                page_elem = gr.HTML(page.create_html(ui.tabname))
                page_elem.change(fn=lambda: None, _js=f'() => refreshExtraNetworks("{tabname}")', inputs=[], outputs=[])
                ui.pages.append(page_elem)

    def toggle_visibility(is_visible):
        is_visible = not is_visible
        return is_visible, gr.update(visible=is_visible), gr.update(variant=("secondary-down" if is_visible else "secondary"))

    state_visible = gr.State(value=False) # pylint: disable=abstract-class-instantiated
    button.click(fn=toggle_visibility, inputs=[state_visible], outputs=[state_visible, container, button])
    button_close.click(fn=toggle_visibility, inputs=[state_visible], outputs=[state_visible, container])

    def refresh():
        res = []
        for pg in ui.stored_extra_pages:
            pg.refresh()
            res.append(pg.create_html(ui.tabname))
        ui.search.update(value = ui.search.value)
        return res

    button_refresh.click(fn=refresh, inputs=[], outputs=ui.pages)
    return ui


def path_is_parent(parent_path, child_path):
    parent_path = os.path.abspath(parent_path)
    child_path = os.path.abspath(child_path)
    return child_path.startswith(parent_path)


def setup_ui(ui, gallery):
    def save_preview(index, images, filename):
        if len(images) == 0:
            print("There is no image in gallery to save as a preview.")
            return [page.create_html(ui.tabname) for page in ui.stored_extra_pages]
        index = int(index)
        index = 0 if index < 0 else index
        index = len(images) - 1 if index >= len(images) else index
        img_info = images[index if index >= 0 else 0]
        image = image_from_url_text(img_info)
        is_allowed = False
        for extra_page in ui.stored_extra_pages:
            if any(path_is_parent(x, filename) for x in extra_page.allowed_directories_for_previews()):
                is_allowed = True
                break
        assert is_allowed, f'writing to {filename} is not allowed'
        image.save(filename)
        shared.log.info(f'Extra network save preview: {filename}')
        return [page.create_html(ui.tabname) for page in ui.stored_extra_pages]

    ui.button_save_preview.click(
        fn=save_preview,
        _js="function(x, y, z){return [selected_gallery_index(), y, z]}",
        inputs=[ui.preview_target_filename, gallery, ui.preview_target_filename],
        outputs=[*ui.pages]
    )

    # write description to a file
    def save_description(filename,descrip):
        lastDotIndex = filename.rindex('.')
        filename = filename[0:lastDotIndex]+".description.txt"
        if descrip != "":
            try:
                with open(filename,'w', encoding='utf-8') as f:
                    f.write(descrip)
                shared.log.info(f'Extra network save description: {filename}')
            except Exception as e:
                shared.log.error(f'Extra network save preview: {filename} {e}')
        return [page.create_html(ui.tabname) for page in ui.stored_extra_pages]

    ui.button_save_description.click(
        fn=save_description,
        _js="function(x,y){return [x,y]}",
        inputs=[ui.description_target_filename, ui.description_input],
        outputs=[*ui.pages]
    )
