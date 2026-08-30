from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
import shutil
import tkinter as tk
from tkinter import messagebox, ttk

from .config import Settings
from .control import Control, StopRequested
from .pipeline import Pipeline
from .progress import format_duration, format_progress


class App(ttk.Frame):
    PAGE_SIZE = 200

    def __init__(self, root: tk.Tk, settings: Settings):
        super().__init__(root, padding=10)
        self.root, self.settings = root, settings
        self.control = Control()
        self.pipeline = Pipeline(settings, self.control)
        self.events: Queue = Queue()
        self.worker: Thread | None = None
        self.review_page = 0
        self.values = {key: tk.StringVar(value="-") for key in (
            "snapshot", "found", "metadata", "allow", "review", "deny", "download",
            "convert", "api_rate", "dl_rate", "disk", "stage_progress", "eta", "current",
        )}
        self.limit = tk.StringVar(value="100")
        self._build()
        self.pack(fill="both", expand=True)
        root.after(250, self._poll)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        ttk.Label(controls, text="テスト上限 (空欄=全件)").pack(side="left")
        ttk.Entry(controls, textvariable=self.limit, width=8).pack(side="left", padx=5)
        self.start_button = ttk.Button(controls, text="開始", command=self.start)
        self.start_button.pack(side="left", padx=3)
        ttk.Button(controls, text="一時停止", command=self.pause).pack(side="left", padx=3)
        ttk.Button(controls, text="再開", command=self.resume).pack(side="left", padx=3)
        ttk.Button(controls, text="安全な停止", command=self.stop).pack(side="left", padx=3)

        status = ttk.LabelFrame(self, text="進捗", padding=8)
        status.pack(fill="x", pady=8)
        labels = [
            ("Dump日付", "snapshot"), ("発見画像数", "found"),
            ("metadata", "metadata"), ("ALLOW", "allow"), ("REVIEW", "review"),
            ("DENY", "deny"), ("ダウンロード", "download"), ("JPEG変換", "convert"),
            ("API速度", "api_rate"), ("DL速度", "dl_rate"),
            ("ディスク空き", "disk"), ("ステージ進捗", "stage_progress"),
            ("残り目安", "eta"),
        ]
        for index, (label, key) in enumerate(labels):
            row, column = divmod(index, 3)
            ttk.Label(status, text=label + ":").grid(row=row, column=column * 2, sticky="e", padx=4, pady=2)
            ttk.Label(status, textvariable=self.values[key], width=24).grid(
                row=row, column=column * 2 + 1, sticky="w", padx=4, pady=2
            )
        detail_row = (len(labels) + 2) // 3
        self.progressbar = ttk.Progressbar(status, maximum=100, mode="determinate")
        self.progressbar.grid(row=detail_row, column=0, columnspan=6, sticky="ew", padx=4, pady=(8, 4))
        ttk.Label(status, text="現在の処理:").grid(
            row=detail_row + 1, column=0, sticky="ne", padx=4, pady=3
        )
        ttk.Label(
            status, textvariable=self.values["current"], wraplength=850, justify="left"
        ).grid(row=detail_row + 1, column=1, columnspan=5, sticky="ew", padx=4, pady=3)
        for column in (1, 3, 5):
            status.columnconfigure(column, weight=1)

        review = ttk.LabelFrame(self, text="REVIEW / DENY", padding=6)
        review.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            review, columns=("state", "title", "license", "reason"), show="headings"
        )
        self.tree.heading("state", text="状態")
        self.tree.heading("title", text="ファイル")
        self.tree.heading("license", text="ライセンス")
        self.tree.heading("reason", text="理由")
        self.tree.column("state", width=75, stretch=False)
        self.tree.column("title", width=260)
        self.tree.column("license", width=150)
        self.tree.column("reason", width=390)
        scroll = ttk.Scrollbar(review, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        pager = ttk.Frame(self)
        pager.pack(fill="x")
        ttk.Button(pager, text="前へ", command=lambda: self._page(-1)).pack(side="left")
        ttk.Button(pager, text="次へ", command=lambda: self._page(1)).pack(side="left", padx=4)
        self.page_label = ttk.Label(pager, text="1")
        self.page_label.pack(side="left")
        self._refresh_review()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            limit = int(self.limit.get()) if self.limit.get().strip() else None
            if limit is not None and limit <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("入力エラー", "上限は正の整数または空欄にしてください")
            return
        self.control = Control()
        self.pipeline = Pipeline(self.settings, self.control)
        self.start_button.configure(state="disabled")
        self.worker = Thread(target=self._run, args=(limit,), daemon=True)
        self.worker.start()

    def _run(self, limit):
        try:
            result = self.pipeline.all(limit=limit, progress=self.events.put)
            self.events.put({"finished": str(result)})
        except StopRequested:
            self.events.put({"stopped": True})
        except Exception as exc:
            self.events.put({"error": str(exc)})

    def pause(self):
        self.control.pause()
        self.values["current"].set("一時停止中")

    def resume(self):
        self.control.resume()

    def stop(self):
        self.control.stop()
        self.values["current"].set("安全な停止を待機中")

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                self._event(event)
        except Empty:
            pass
        try:
            counts = self.pipeline.db.counts()
            self.values["snapshot"].set(str(self.pipeline.db.get_state("snapshot_date", "-")))
            self.values["found"].set(str(counts["found"]))
            self.values["metadata"].set(f"{counts['metadata_done']} / {counts['found']}")
            self.values["allow"].set(str(counts["allow"]))
            self.values["review"].set(str(counts["REVIEW"]))
            self.values["deny"].set(str(counts["DENY"]))
            self.values["download"].set(f"{counts['downloaded']} / {counts['allow']}")
            self.values["convert"].set(f"{counts['converted']} / {counts['allow']}")
            free = shutil.disk_usage(self.settings.workdir).free / 1024**3
            self.values["disk"].set(f"{free:.1f} GiB")
        except Exception:
            pass
        self.root.after(500, self._poll)

    def _event(self, event):
        if "error" in event:
            self.start_button.configure(state="normal")
            messagebox.showerror("処理エラー", event["error"])
            return
        if "finished" in event:
            self.start_button.configure(state="normal")
            self.values["current"].set("完了")
            messagebox.showinfo("完了", event["finished"])
            return
        if event.get("stopped"):
            self.start_button.configure(state="normal")
            self.values["current"].set("安全に停止しました")
            return
        self.values["current"].set(format_progress(event))
        done, total = event.get("done"), event.get("total")
        if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0:
            percent = min(100.0, max(0.0, done / total * 100))
            self.progressbar.configure(value=percent)
            self.values["stage_progress"].set(f"{percent:.1f}%")
            elapsed = event.get("elapsed")
            if isinstance(elapsed, (int, float)) and 0 < done < total:
                rate = event.get("rate")
                if isinstance(rate, (int, float)) and rate > 0 and event.get("unit") != "bytes":
                    eta = (total - done) / rate
                elif not event.get("processed"):
                    eta = elapsed * (total - done) / done
                else:
                    eta = None
                self.values["eta"].set("-" if eta is None else f"約 {format_duration(eta)}")
            else:
                self.values["eta"].set("-")
        else:
            self.progressbar.configure(value=0)
            self.values["stage_progress"].set("件数を計測中")
            self.values["eta"].set("-")
        if "api_rate" in event:
            self.values["api_rate"].set(f"{event['api_rate']:.2f} images/s")
        if "dl_mbps" in event:
            self.values["dl_rate"].set(f"{event['dl_mbps']:.2f} Mbps")
        if event.get("stage") == "classify":
            self._refresh_review()

    def _page(self, delta):
        self.review_page = max(0, self.review_page + delta)
        self._refresh_review()

    def _refresh_review(self):
        self.tree.delete(*self.tree.get_children())
        with self.pipeline.db.connect() as conn:
            rows = conn.execute(
                "SELECT classification,dump_title,license_short_name,classification_reason FROM images "
                "WHERE classification IN ('REVIEW','DENY') ORDER BY id LIMIT ? OFFSET ?",
                (self.PAGE_SIZE, self.review_page * self.PAGE_SIZE),
            ).fetchall()
        for row in rows:
            self.tree.insert("", "end", values=tuple(row))
        self.page_label.configure(text=str(self.review_page + 1))

    def _close(self):
        if self.worker and self.worker.is_alive():
            self.control.stop()
            messagebox.showinfo("安全な停止", "停止を要求しました。処理が停止してからもう一度閉じてください。")
            return
        self.root.destroy()


def run_gui(settings: Settings) -> None:
    root = tk.Tk()
    root.title("XTBook 日本語Wikipedia画像辞書ビルダー")
    root.geometry("1050x680")
    App(root, settings)
    root.mainloop()
