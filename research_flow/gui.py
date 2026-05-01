from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from .config import AppConfig
from .pipeline import IngestRequest, extract_prefill, run_ingest_pipeline

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None


DEFAULT_CONFIG_PATH = Path("research-flow.config.json")
WORKSPACE_IMPORT_DIR = Path("imports")


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _preferred_file_dialog_dir(current_path: str = "") -> str:
    if current_path:
        candidate = Path(current_path).expanduser()
        if candidate.exists():
            return str(candidate.parent if candidate.is_file() else candidate)
    return str(Path.home())


def copy_pdf_into_workspace(source_path: Path, workspace_dir: Path = WORKSPACE_IMPORT_DIR) -> Path:
    source = source_path.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    destination = workspace_dir / source.name
    if destination.exists():
        stem = source.stem
        suffix = source.suffix or ".pdf"
        counter = 2
        while True:
            candidate = workspace_dir / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                destination = candidate
                break
            counter += 1
    shutil.copy2(source, destination)
    return destination.resolve()


class ResearchFlowApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Research Flow")
        self.root.geometry("1180x920")
        self.root.minsize(1040, 820)
        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.root.report_callback_exception = self._report_callback_exception

        self.config_path_var = tk.StringVar(value=str(DEFAULT_CONFIG_PATH))
        self.pdf_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready.")
        self.config_vars: Dict[str, tk.StringVar] = {
            "zotero_user_id": tk.StringVar(),
            "zotero_api_key": tk.StringVar(),
            "zotero_library_type": tk.StringVar(value="users"),
            "zotero_collection_key": tk.StringVar(),
            "openai_api_key": tk.StringVar(),
            "openai_model": tk.StringVar(value="gpt-5.4"),
            "obsidian_vault_path": tk.StringVar(),
            "obsidian_rest_url": tk.StringVar(),
            "obsidian_rest_api_key": tk.StringVar(),
            "packet_dir": tk.StringVar(),
            "note_subdir": tk.StringVar(value="Literature"),
            "default_item_type": tk.StringVar(value="journalArticle"),
            "default_status": tk.StringVar(value="inbox"),
        }
        self.paper_vars: Dict[str, tk.StringVar] = {
            "title": tk.StringVar(),
            "authors": tk.StringVar(),
            "year": tk.StringVar(),
            "journal": tk.StringVar(),
            "doi": tk.StringVar(),
            "url": tk.StringVar(),
            "tags": tk.StringVar(),
            "status": tk.StringVar(value="inbox"),
            "item_type": tk.StringVar(value="journalArticle"),
        }
        self.abstract_text: Optional[tk.Text] = None
        self.annotation_text: Optional[tk.Text] = None
        self.log_text: Optional[tk.Text] = None
        self.run_button: Optional[ttk.Button] = None
        self.drop_label: Optional[tk.Label] = None

        self._build_ui()
        self._load_config_if_present()
        self.root.after(150, self._poll_queue)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(7, weight=1)

        self._build_header(container)
        self._build_settings_section(container)
        self._build_pdf_section(container)
        self._build_metadata_section(container)
        self._build_notes_section(container)
        self._build_actions(container)
        self._build_log_section(container)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Config File").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(header, textvariable=self.config_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(header, text="Load", command=self.load_config).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(header, text="Save", command=self.save_config).grid(row=0, column=3, padx=(8, 0))

        helper = (
            "Use Browse to pick any PDF on your Mac. Use Import To Workspace to copy it into "
            f"{WORKSPACE_IMPORT_DIR}/ inside this project."
        )
        ttk.Label(
            parent,
            text=helper,
            wraplength=1080,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(10, 14))

    def _build_settings_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Connections", padding=12)
        section.grid(row=2, column=0, sticky="ew")
        for column in range(4):
            section.columnconfigure(column, weight=1 if column in {1, 3} else 0)

        left_fields = [
            ("Zotero User ID", "zotero_user_id"),
            ("Library Type", "zotero_library_type"),
            ("Collection Key", "zotero_collection_key"),
            ("Default Item Type", "default_item_type"),
            ("Default Status", "default_status"),
            ("Note Subdirectory", "note_subdir"),
        ]
        right_fields = [
            ("Zotero API Key", "zotero_api_key"),
            ("OpenAI API Key", "openai_api_key"),
            ("OpenAI Model", "openai_model"),
            ("Obsidian Vault Path", "obsidian_vault_path"),
            ("Obsidian REST URL", "obsidian_rest_url"),
            ("Obsidian REST API Key", "obsidian_rest_api_key"),
            ("Packet Directory", "packet_dir"),
        ]

        for row, (label, key) in enumerate(left_fields):
            ttk.Label(section, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            show = "*" if "key" in key and "collection" not in key else None
            ttk.Entry(section, textvariable=self.config_vars[key], show=show).grid(
                row=row, column=1, sticky="ew", padx=(0, 18), pady=4
            )

        for row, (label, key) in enumerate(right_fields):
            ttk.Label(section, text=label).grid(row=row, column=2, sticky="w", padx=(0, 8), pady=4)
            show = "*" if "key" in key and "collection" not in key else None
            ttk.Entry(section, textvariable=self.config_vars[key], show=show).grid(
                row=row, column=3, sticky="ew", pady=4
            )

    def _build_pdf_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="PDF Source", padding=12)
        section.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        section.columnconfigure(0, weight=1)

        drop_text = (
            "Drop a PDF here"
            if TkinterDnD and DND_FILES
            else "Drag-and-drop is unavailable. Use Browse or Import To Workspace."
        )
        self.drop_label = tk.Label(
            section,
            text=drop_text,
            height=3,
            relief="groove",
            anchor="center",
        )
        self.drop_label.grid(row=0, column=0, columnspan=5, sticky="ew")
        if TkinterDnD and DND_FILES:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._handle_drop)

        ttk.Label(
            section,
            text="The selected file path appears below. Import To Workspace copies the PDF into this repo.",
            wraplength=1040,
            justify="left",
        ).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 10))

        section.columnconfigure(0, weight=1)
        ttk.Entry(section, textvariable=self.pdf_path_var).grid(row=2, column=0, sticky="ew")
        ttk.Button(section, text="Browse", command=self.browse_pdf).grid(row=2, column=1, padx=(8, 0))
        ttk.Button(section, text="Import To Workspace", command=self.import_pdf_to_workspace).grid(
            row=2, column=2, padx=(8, 0)
        )
        ttk.Button(section, text="Autofill", command=self.autofill_from_pdf).grid(row=2, column=3, padx=(8, 0))

    def _build_metadata_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Paper Metadata", padding=12)
        section.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        for column in range(4):
            section.columnconfigure(column, weight=1 if column in {1, 3} else 0)

        ttk.Label(section, text="Title").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.paper_vars["title"]).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=4
        )

        ttk.Label(section, text="Authors").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.paper_vars["authors"]).grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=4
        )

        pairs = [
            ("Year", "year", "Journal", "journal"),
            ("DOI", "doi", "URL", "url"),
            ("Tags", "tags", "Status", "status"),
            ("Item Type", "item_type", "", ""),
        ]
        start_row = 2
        for offset, (l1, k1, l2, k2) in enumerate(pairs):
            row = start_row + offset
            ttk.Label(section, text=l1).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(section, textvariable=self.paper_vars[k1]).grid(
                row=row, column=1, sticky="ew", padx=(0, 18), pady=4
            )
            if l2:
                ttk.Label(section, text=l2).grid(row=row, column=2, sticky="w", padx=(0, 8), pady=4)
                ttk.Entry(section, textvariable=self.paper_vars[k2]).grid(
                    row=row, column=3, sticky="ew", pady=4
                )

    def _build_notes_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Abstract and Notes", padding=12)
        section.grid(row=5, column=0, sticky="nsew", pady=(14, 0))
        section.columnconfigure(0, weight=1)
        section.columnconfigure(1, weight=1)
        section.rowconfigure(1, weight=1)
        section.rowconfigure(3, weight=1)

        ttk.Label(section, text="Abstract").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(section, text="Annotation Summary").grid(row=0, column=1, sticky="w", pady=(0, 6))

        self.abstract_text = tk.Text(section, height=8, wrap="word")
        self.abstract_text.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.annotation_text = tk.Text(section, height=8, wrap="word")
        self.annotation_text.grid(row=1, column=1, sticky="nsew")

        ttk.Label(
            section,
            text="Paste the abstract and any useful highlights or summary notes before running the pipeline.",
            wraplength=1040,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 6))

    def _build_actions(self, parent: ttk.Frame) -> None:
        section = ttk.Frame(parent)
        section.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        section.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(section, text="Run Pipeline", command=self.run_pipeline)
        self.run_button.grid(row=0, column=0, sticky="w")
        ttk.Label(section, textvariable=self.status_var).grid(row=0, column=1, sticky="w", padx=(14, 0))

    def _build_log_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Progress Log", padding=12)
        section.grid(row=7, column=0, sticky="nsew", pady=(14, 0))
        section.columnconfigure(0, weight=1)
        section.rowconfigure(0, weight=1)

        self.log_text = tk.Text(section, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(section, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _append_log(self, message: str) -> None:
        if not self.log_text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:  # pragma: no cover - GUI path
        message = f"{exc_type.__name__}: {exc_value}"
        self._append_log(f"Callback error: {message}")
        self.status_var.set("Unexpected GUI error.")
        try:
            messagebox.showerror("Unexpected GUI Error", message, parent=self.root)
        except Exception:
            pass

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)
        self._append_log(message)

    def _open_pdf_dialog(self) -> str:
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a PDF",
            initialdir=_preferred_file_dialog_dir(self.pdf_path_var.get().strip()),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*")],
        )
        self.root.lift()
        return selected

    def _handle_drop(self, event) -> None:  # pragma: no cover - GUI interaction
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        self.pdf_path_var.set(raw)
        self._set_status(f"PDF selected from drag-and-drop: {raw}")
        self.autofill_from_pdf()

    def browse_pdf(self) -> None:
        self._set_status("Opening PDF picker...")
        selected = self._open_pdf_dialog()
        if selected:
            self.pdf_path_var.set(selected)
            self._set_status(f"Selected PDF: {selected}")
        else:
            self.status_var.set("Browse cancelled.")

    def import_pdf_to_workspace(self) -> None:
        self._set_status("Opening PDF picker for import...")
        selected = self._open_pdf_dialog()
        if not selected:
            self.status_var.set("Import cancelled.")
            return
        try:
            imported = copy_pdf_into_workspace(Path(selected))
        except Exception as exc:
            self._append_log(f"Import failed: {exc}")
            messagebox.showerror("Import Failed", str(exc), parent=self.root)
            return
        self.pdf_path_var.set(str(imported))
        self._set_status(f"Imported PDF into workspace: {imported}")
        self.autofill_from_pdf()

    def autofill_from_pdf(self) -> None:
        pdf_path = self.pdf_path_var.get().strip()
        if not pdf_path:
            messagebox.showerror("Missing PDF", "Choose a PDF first.", parent=self.root)
            return
        try:
            request = extract_prefill(Path(pdf_path))
        except Exception as exc:
            self._append_log(f"Autofill failed: {exc}")
            messagebox.showerror("Autofill Failed", str(exc), parent=self.root)
            return
        self.paper_vars["title"].set(request.title)
        self.paper_vars["authors"].set(", ".join(request.authors))
        self.paper_vars["year"].set(request.year or "")
        self.paper_vars["url"].set(request.url or "")
        if not self.paper_vars["status"].get().strip():
            self.paper_vars["status"].set(self.config_vars["default_status"].get())
        if not self.paper_vars["item_type"].get().strip():
            self.paper_vars["item_type"].set(self.config_vars["default_item_type"].get())
        self._set_status("Metadata prefilled from PDF and filename heuristics.")

    def _collect_config(self) -> AppConfig:
        data = {key: value.get().strip() or None for key, value in self.config_vars.items()}
        data["zotero_library_type"] = self.config_vars["zotero_library_type"].get().strip() or "users"
        data["openai_model"] = self.config_vars["openai_model"].get().strip() or "gpt-5.4"
        data["note_subdir"] = self.config_vars["note_subdir"].get().strip() or "Literature"
        data["default_item_type"] = self.config_vars["default_item_type"].get().strip() or "journalArticle"
        data["default_status"] = self.config_vars["default_status"].get().strip() or "inbox"
        data["zotero_user_id"] = self.config_vars["zotero_user_id"].get().strip()
        data["zotero_api_key"] = self.config_vars["zotero_api_key"].get().strip()
        return AppConfig.from_dict(data)

    def _collect_request(self) -> IngestRequest:
        if not self.abstract_text or not self.annotation_text:
            raise RuntimeError("GUI text widgets are not initialized")
        return IngestRequest(
            pdf_path=Path(self.pdf_path_var.get().strip()),
            title=self.paper_vars["title"].get().strip(),
            authors=_split_csv(self.paper_vars["authors"].get()),
            year=self.paper_vars["year"].get().strip() or None,
            journal=self.paper_vars["journal"].get().strip() or None,
            doi=self.paper_vars["doi"].get().strip() or None,
            url=self.paper_vars["url"].get().strip() or None,
            abstract=self.abstract_text.get("1.0", "end").strip() or None,
            annotation_text=self.annotation_text.get("1.0", "end").strip() or None,
            tags=_split_csv(self.paper_vars["tags"].get()),
            status=self.paper_vars["status"].get().strip() or "inbox",
            item_type=self.paper_vars["item_type"].get().strip() or "journalArticle",
        )

    def load_config(self) -> None:
        try:
            config = AppConfig.from_path(Path(self.config_path_var.get()))
        except Exception as exc:
            self._append_log(f"Load failed: {exc}")
            messagebox.showerror("Load Failed", str(exc), parent=self.root)
            return
        for key, var in self.config_vars.items():
            value = getattr(config, key)
            var.set("" if value is None else str(value))
        self._set_status(f"Config loaded from {self.config_path_var.get()}")

    def save_config(self) -> None:
        try:
            config = self._collect_config()
            config.save(Path(self.config_path_var.get()))
        except Exception as exc:
            self._append_log(f"Save failed: {exc}")
            messagebox.showerror("Save Failed", str(exc), parent=self.root)
            return
        self._set_status(f"Config saved to {self.config_path_var.get()}")

    def _load_config_if_present(self) -> None:
        if Path(self.config_path_var.get()).exists():
            self.load_config()

    def run_pipeline(self) -> None:
        try:
            config = self._collect_config()
            request = self._collect_request()
            if not request.pdf_path.exists():
                raise FileNotFoundError(f"PDF not found: {request.pdf_path}")
            if not request.title:
                raise ValueError("Title is required")
            if not request.authors:
                raise ValueError("At least one author is required")
        except Exception as exc:
            self._append_log(f"Validation failed: {exc}")
            messagebox.showerror("Invalid Input", str(exc), parent=self.root)
            return

        if self.run_button:
            self.run_button.state(["disabled"])
        self._set_status("Running pipeline...")

        def worker() -> None:
            try:
                result = run_ingest_pipeline(
                    request,
                    config,
                    progress=lambda msg: self.queue.put(("progress", msg)),
                )
                self.queue.put(("done", result))
            except Exception as exc:  # pragma: no cover - GUI threading
                self.queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self._set_status(str(payload))
                elif kind == "done":
                    if self.run_button:
                        self.run_button.state(["!disabled"])
                    result = payload
                    self._set_status("Pipeline complete.")
                    summary = "\n".join(
                        [
                            f"Citekey: {result.citekey}",
                            f"Packet: {result.packet_path}",
                            f"Analysis: {result.analysis_path}",
                            f"Note: {result.note_path or result.obsidian_target}",
                        ]
                    )
                    self._append_log(summary)
                    messagebox.showinfo("Done", summary, parent=self.root)
                elif kind == "error":
                    if self.run_button:
                        self.run_button.state(["!disabled"])
                    self._append_log(f"Pipeline failed: {payload}")
                    self.status_var.set("Pipeline failed.")
                    messagebox.showerror("Pipeline Failed", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def launch_gui() -> None:
    if TkinterDnD and DND_FILES:  # pragma: no cover - depends on optional package
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    ResearchFlowApp(root)
    root.mainloop()
