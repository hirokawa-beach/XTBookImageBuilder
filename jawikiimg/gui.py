from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
import shutil
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import webbrowser

from .config import Settings
from .control import Control, StopRequested
from .manual_review import approve_reviews, clear_manual_decisions, deny_reviews
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
        self.review_rows: dict[int, dict] = {}
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

        review = ttk.LabelFrame(self, text="REVIEW / DENY / 手動判定", padding=6)
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
        self.tree.bind("<<TreeviewSelect>>", self._show_review_detail)
        self.tree.bind("<Double-1>", lambda _event: self._open_description())
        pager = ttk.Frame(self)
        pager.pack(fill="x")
        ttk.Button(pager, text="前へ", command=lambda: self._page(-1)).pack(side="left")
        ttk.Button(pager, text="次へ", command=lambda: self._page(1)).pack(side="left", padx=4)
        self.page_label = ttk.Label(pager, text="1")
        self.page_label.pack(side="left")
        ttk.Button(pager, text="選択を手動承認", command=self._approve_selected).pack(side="left", padx=(18, 4))
        ttk.Button(pager, text="選択を手動DENY", command=self._deny_selected).pack(side="left", padx=4)
        ttk.Button(pager, text="手動判定を解除", command=self._clear_selected).pack(side="left", padx=4)
        ttk.Button(pager, text="説明ページを開く", command=self._open_description).pack(side="left", padx=4)

        detail = ttk.LabelFrame(self, text="選択画像の判断材料", padding=6)
        detail.pack(fill="x", pady=(6, 0))
        self.review_detail = tk.Text(detail, height=8, wrap="word")
        detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.review_detail.yview)
        self.review_detail.configure(yscrollcommand=detail_scroll.set, state="disabled")
        self.review_detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="left", fill="y")
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
        self.review_rows.clear()
        with self.pipeline.db.connect() as conn:
            rows = conn.execute(
                """SELECT id,classification,dump_title,license_short_name,classification_reason,
                manual_override,manual_note,license_url,description_url,artist,attribution,credit,
                permission,restrictions_text FROM images
                WHERE classification IN ('REVIEW','DENY') OR manual_override IS NOT NULL
                ORDER BY id LIMIT ? OFFSET ?""",
                (self.PAGE_SIZE, self.review_page * self.PAGE_SIZE),
            ).fetchall()
        for row in rows:
            data = dict(row)
            image_id = int(data["id"])
            self.review_rows[image_id] = data
            state = data["classification"] + (" (手動)" if data["manual_override"] else "")
            self.tree.insert(
                "", "end", iid=str(image_id),
                values=(state, data["dump_title"], data["license_short_name"], data["classification_reason"]),
            )
        self.page_label.configure(text=str(self.review_page + 1))
        self._set_review_detail("")

    def _selected_review_ids(self) -> tuple[int, ...]:
        return tuple(int(iid) for iid in self.tree.selection())

    def _review_action_ready(self) -> bool:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("処理中", "処理を安全に停止してから手動判定してください。")
            return False
        if not self.tree.selection():
            messagebox.showinfo("未選択", "画像を1件以上選択してください。")
            return False
        return True

    def _approve_selected(self):
        if not self._review_action_ready():
            return
        selected = self._selected_review_ids()
        if not messagebox.askyesno(
            "手動承認の確認",
            f"選択した{len(selected)}件を辞書へ収録可能として承認します。\n"
            "ライセンス、Permission、Restrictions、説明ページを確認しましたか？",
        ):
            return
        note = simpledialog.askstring("確認メモ", "承認根拠または確認内容を入力してください（空欄可）:")
        if note is None:
            return
        try:
            count = approve_reviews(self.pipeline.db, selected, note)
        except ValueError as exc:
            messagebox.showerror("承認できません", str(exc))
            return
        self._refresh_review()
        messagebox.showinfo(
            "手動承認",
            f"{count}件を手動承認しました。画像を収録するには、開始ボタンで処理を再開してください。",
        )

    def _deny_selected(self):
        if not self._review_action_ready():
            return
        selected = self._selected_review_ids()
        note = simpledialog.askstring("手動DENY", "収録しない理由を入力してください（空欄可）:")
        if note is None:
            return
        try:
            count = deny_reviews(self.pipeline.db, selected, note)
        except ValueError as exc:
            messagebox.showerror("手動DENYできません", str(exc))
            return
        self._refresh_review()
        messagebox.showinfo("手動DENY", f"{count}件を手動DENYにしました。")

    def _clear_selected(self):
        if not self._review_action_ready():
            return
        selected = self._selected_review_ids()
        if not messagebox.askyesno("手動判定を解除", f"選択した{len(selected)}件を自動判定へ戻しますか？"):
            return
        try:
            count = clear_manual_decisions(self.pipeline.db, selected)
        except ValueError as exc:
            messagebox.showerror("解除できません", str(exc))
            return
        self._refresh_review()
        messagebox.showinfo("手動判定を解除", f"{count}件を自動判定へ戻しました。")

    def _show_review_detail(self, _event=None):
        selected = self._selected_review_ids()
        if not selected:
            self._set_review_detail("")
            return
        row = self.review_rows.get(selected[0], {})
        creator = row.get("attribution") or row.get("artist") or row.get("credit") or ""
        lines = (
            f"ファイル: {row.get('dump_title') or ''}",
            f"状態: {row.get('classification') or ''}",
            f"ライセンス: {row.get('license_short_name') or ''}",
            f"ライセンスURL: {row.get('license_url') or ''}",
            f"作者 / Attribution: {creator}",
            f"判定理由: {row.get('classification_reason') or ''}",
            f"Permission: {row.get('permission') or ''}",
            f"Restrictions: {row.get('restrictions_text') or ''}",
            f"説明ページ: {row.get('description_url') or ''}",
            f"手動メモ: {row.get('manual_note') or ''}",
        )
        self._set_review_detail("\n".join(lines))

    def _set_review_detail(self, value: str):
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert("1.0", value)
        self.review_detail.configure(state="disabled")

    def _open_description(self):
        selected = self._selected_review_ids()
        if not selected:
            messagebox.showinfo("未選択", "画像を1件選択してください。")
            return
        url = self.review_rows.get(selected[0], {}).get("description_url")
        if not url:
            messagebox.showinfo("URLなし", "Wikimediaの説明ページURLがありません。")
            return
        webbrowser.open(str(url))

    def _close(self):
        if self.worker and self.worker.is_alive():
            self.control.stop()
            messagebox.showinfo("安全な停止", "停止を要求しました。処理が停止してからもう一度閉じてください。")
            return
        self.root.destroy()


def run_gui(settings: Settings) -> None:
    root = tk.Tk()
    root.title("XTBook 日本語Wikipedia画像辞書ビルダー")
    root.geometry("1150x820")
    App(root, settings)
    root.mainloop()
