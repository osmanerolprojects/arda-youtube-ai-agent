
import os
import random
import sqlite3
import threading
import webbrowser
import tkinter as tk

from tkinter import ttk, messagebox

from main_agent import (
    initialize_database,
    search_youtube,
    get_video_description,
)
from langgraph_agent import agent, SIGNATURE, PRAISES
from youtube_post import (
    ensure_post_log,
    already_posted,
    post_one_comment,
    record_success,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "videos.db")

BG = "#f3f5f9"
NAVY = "#18243a"
BLUE = "#2458a6"
GREEN = "#21834a"
RED = "#b83c3c"


class ArdaDashboard:

    def __init__(self, root):
        self.root = root
        self.root.title("ARDA AI AGENT")
        self.root.geometry("1100x800")
        self.root.minsize(850, 650)

        initialize_database()
        ensure_post_log()

        self.busy = False
        self.current_id = None
        self.rows = {}
        self.active_tab = "review"

        self.build_ui()
        self.refresh()
        self.root.after(3000, self.auto_refresh)

    def connect(self):
        return sqlite3.connect(DB_PATH, timeout=15)

    def build_ui(self):
        self.root.configure(bg=BG)

        header = tk.Frame(self.root, bg=NAVY)
        header.pack(fill="x")

        tk.Label(
            header,
            text="👑 ARDA AI AGENT",
            font=("Segoe UI", 22, "bold"),
            bg=NAVY,
            fg="white"
        ).pack(pady=(14, 2))

        tk.Label(
            header,
            text="YouTube AI Video & Comment Manager",
            font=("Segoe UI", 10),
            bg=NAVY,
            fg="#d4dfee"
        ).pack(pady=(0, 14))

        stats_frame = tk.Frame(self.root, bg=BG)
        stats_frame.pack(fill="x", padx=16, pady=10)

        self.stats = {}

        for key, label in [
            ("pending_review", "ONAY BEKLEYEN"),
            ("missing", "EKSİK TASLAK"),
            ("queue", "ANALİZ KUYRUĞU"),
            ("posted", "YAYIMLANAN"),
            ("rejected", "REDDEDİLEN"),
        ]:
            frame = tk.Frame(
                stats_frame, bg="white",
                bd=1, relief="solid"
            )
            frame.pack(
                side="left", expand=True,
                fill="x", padx=3
            )

            value = tk.Label(
                frame, text="0",
                font=("Segoe UI", 20, "bold"),
                bg="white", fg=NAVY
            )
            value.pack(pady=(7, 0))

            tk.Label(
                frame, text=label,
                font=("Segoe UI", 8),
                bg="white", fg="#526177"
            ).pack(pady=(0, 7))

            self.stats[key] = value

        controls = tk.Frame(self.root, bg=BG)
        controls.pack(fill="x", padx=16, pady=5)

        self.search_btn = tk.Button(
            controls,
            text="YENİ VİDEO ARA",
            command=lambda: self.start_analysis(True),
            bg=BLUE, fg="white",
            padx=12, pady=8
        )
        self.search_btn.pack(side="left", padx=3)

        self.analyze_btn = tk.Button(
            controls,
            text="KUYRUĞU ANALİZ ET",
            command=lambda: self.start_analysis(False),
            bg=GREEN, fg="white",
            padx=12, pady=8
        )
        self.analyze_btn.pack(side="left", padx=3)

        self.repair_btn = tk.Button(
            controls,
            text="EKSİK TASLAKLARI OLUŞTUR",
            command=self.repair_drafts,
            bg="#7752a8", fg="white",
            padx=12, pady=8
        )
        self.repair_btn.pack(side="left", padx=3)

        tk.Button(
            controls,
            text="YENİLE",
            command=self.refresh,
            padx=12, pady=8
        ).pack(side="right", padx=3)

        status_frame = tk.Frame(self.root, bg=BG)
        status_frame.pack(fill="x", padx=20, pady=7)

        self.state_label = tk.Label(
            status_frame,
            text="● BEKLEMEDE",
            font=("Segoe UI", 10, "bold"),
            bg=BG, fg="#667085"
        )
        self.state_label.pack(anchor="w")

        self.activity_label = tk.Label(
            status_frame,
            text="Hazır",
            bg=BG, fg="#526177",
            wraplength=1000,
            justify="left"
        )
        self.activity_label.pack(anchor="w", pady=3)

        self.progress = ttk.Progressbar(
            status_frame,
            mode="indeterminate"
        )
        self.progress.pack(fill="x", pady=4)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(
            fill="both", expand=True,
            padx=18, pady=7
        )

        self.trees = {}

        for key, title in [
            ("review", "İNCELENECEK YORUMLAR"),
            ("queue", "ANALİZ / EKSİK TASLAK"),
            ("history", "GEÇMİŞ"),
        ]:
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text="  " + title + "  ")

            tree = ttk.Treeview(
                frame,
                columns=("title", "status"),
                show="headings",
                selectmode="browse",
                height=7
            )

            tree.heading("title", text="Video")
            tree.heading("status", text="Durum")
            tree.column("title", width=760)
            tree.column(
                "status", width=170,
                anchor="center"
            )

            scrollbar = ttk.Scrollbar(
                frame,
                orient="vertical",
                command=tree.yview
            )
            tree.configure(
                yscrollcommand=scrollbar.set
            )

            tree.pack(
                side="left", fill="both",
                expand=True, padx=(5, 0), pady=5
            )
            scrollbar.pack(
                side="right", fill="y", pady=5
            )

            tree.bind(
                "<<TreeviewSelect>>",
                lambda event, k=key: self.select_video(k)
            )

            self.trees[key] = tree

        detail = tk.LabelFrame(
            self.root,
            text="Video ve Yorum",
            bg=BG,
            font=("Segoe UI", 10, "bold"),
            padx=12, pady=8
        )
        detail.pack(fill="x", padx=18, pady=7)

        self.title_label = tk.Label(
            detail,
            text="Bir video seç",
            font=("Segoe UI", 10, "bold"),
            bg=BG,
            wraplength=1000,
            justify="left"
        )
        self.title_label.pack(anchor="w", pady=4)

        self.reason_label = tk.Label(
            detail,
            text="",
            bg=BG, fg="#526177",
            wraplength=1000,
            justify="left"
        )
        self.reason_label.pack(anchor="w", pady=3)

        tk.Button(
            detail,
            text="▶ VİDEOYU YOUTUBE'DA İZLE",
            command=self.open_video,
            bg="#c4302b", fg="white",
            pady=6
        ).pack(fill="x", pady=5)

        self.comment_text = tk.Text(
            detail,
            height=3,
            font=("Segoe UI", 11),
            wrap="word"
        )
        self.comment_text.pack(fill="x", pady=6)

        actions = tk.Frame(detail, bg=BG)
        actions.pack(fill="x", pady=5)

        self.approve_btn = tk.Button(
            actions,
            text="✓ ONAYLA",
            command=self.approve,
            bg=GREEN, fg="white",
            width=15, pady=7
        )
        self.approve_btn.pack(side="left", padx=4)

        self.reject_btn = tk.Button(
            actions,
            text="✕ REDDET",
            command=self.reject,
            bg=RED, fg="white",
            width=15, pady=7
        )
        self.reject_btn.pack(side="left", padx=4)

        self.post_btn = tk.Button(
            actions,
            text="➤ YOUTUBE'A GÖNDER",
            command=self.post,
            bg=BLUE, fg="white",
            width=23, pady=7
        )
        self.post_btn.pack(side="right", padx=4)

        self.update_buttons()

    def get_rows(self):
        with self.connect() as db:
            return db.execute("""
                SELECT
                    v.video_id,
                    v.title,
                    v.status,
                    COALESCE(c.comment, ''),
                    COALESCE(c.review_status, 'no_draft'),
                    r.decision,
                    COALESCE(r.reason, '')
                FROM videos v
                LEFT JOIN comment_drafts c
                    ON v.video_id = c.video_id
                LEFT JOIN langgraph_results r
                    ON v.video_id = r.video_id
                ORDER BY v.discovered_at DESC
            """).fetchall()

    def refresh(self):
        data = self.get_rows()
        selected = self.current_id
        self.rows = {}

        counts = {
            "pending_review": 0,
            "missing": 0,
            "queue": 0,
            "posted": 0,
            "rejected": 0
        }

        for tree in self.trees.values():
            for item in tree.get_children():
                tree.delete(item)

        for row in data:
            video_id, title, video_status, comment, status, decision, reason = row
            self.rows[video_id] = row

            missing = (
                decision == "relevant"
                and status == "no_draft"
            )

            if status in counts:
                counts[status] += 1

            if decision is None:
                counts["queue"] += 1

            if missing:
                counts["missing"] += 1

            if status in ("pending_review", "approved"):
                tab = "review"
                display_status = status

            elif decision is None or missing:
                tab = "queue"
                display_status = (
                    "missing_draft"
                    if missing else "waiting_analysis"
                )

            else:
                tab = "history"
                display_status = (
                    status if status != "no_draft"
                    else decision
                )

            self.trees[tab].insert(
                "", "end",
                iid=video_id,
                values=(title, display_status)
            )

        for key, value in counts.items():
            self.stats[key].config(text=str(value))

        if selected in self.rows:
            self.display_video(selected)
        else:
            self.current_id = None
            self.title_label.config(text="Bir video seç")
            self.reason_label.config(text="")
            self.comment_text.config(state="normal")
            self.comment_text.delete("1.0", "end")
            self.update_buttons()

    def auto_refresh(self):
        if not self.busy:
            self.refresh()
        self.root.after(3000, self.auto_refresh)

    def select_video(self, tab):
        selection = self.trees[tab].selection()
        if selection:
            self.display_video(selection[0])

    def display_video(self, video_id):
        self.current_id = video_id

        row = self.rows[video_id]
        title = row[1]
        comment = row[3]
        decision = row[5]
        reason = row[6]

        self.title_label.config(text=title)
        self.reason_label.config(
            text=f"AI kararı: {decision or 'Bekliyor'} | {reason}"
        )

        self.comment_text.config(state="normal")
        self.comment_text.delete("1.0", "end")
        self.comment_text.insert("1.0", comment)

        self.update_buttons()

    def update_buttons(self):
        row = self.rows.get(self.current_id)
        status = row[4] if row else None

        can_review = (
            status == "pending_review"
            and not self.busy
        )
        can_post = (
            status == "approved"
            and not self.busy
        )

        self.comment_text.config(
            state="normal" if can_review else "disabled"
        )
        self.approve_btn.config(
            state="normal" if can_review else "disabled"
        )
        self.reject_btn.config(
            state="normal" if can_review else "disabled"
        )
        self.post_btn.config(
            state="normal" if can_post else "disabled"
        )

        for button in (
            self.search_btn,
            self.analyze_btn,
            self.repair_btn
        ):
            button.config(
                state="disabled" if self.busy else "normal"
            )

    def open_video(self):
        if self.current_id:
            webbrowser.open(
                "https://www.youtube.com/watch?v="
                + self.current_id
            )

    def approve(self):
        row = self.rows.get(self.current_id)
        if not row or row[4] != "pending_review":
            return

        comment = self.comment_text.get(
            "1.0", "end-1c"
        ).strip()

        if not comment:
            messagebox.showwarning(
                "Uyarı", "Yorum boş olamaz."
            )
            return

        with self.connect() as db:
            cursor = db.execute("""
                UPDATE comment_drafts
                SET comment = ?, review_status = 'approved'
                WHERE video_id = ?
                  AND review_status = 'pending_review'
            """, (comment, self.current_id))

        if cursor.rowcount:
            messagebox.showinfo(
                "Onaylandı",
                "Yorum onaylandı ama henüz gönderilmedi."
            )

        self.refresh()

    def reject(self):
        row = self.rows.get(self.current_id)
        if not row or row[4] != "pending_review":
            return

        with self.connect() as db:
            db.execute("""
                UPDATE comment_drafts
                SET review_status = 'rejected'
                WHERE video_id = ?
                  AND review_status = 'pending_review'
            """, (self.current_id,))

        self.refresh()

    def open_job(self, text):
        if self.busy:
            return False

        self.busy = True
        self.state_label.config(
            text="● ÇALIŞIYOR", fg=GREEN
        )
        self.activity_label.config(text=text)
        self.progress.start(12)
        self.update_buttons()
        return True

    def set_activity(self, text):
        self.root.after(
            0,
            lambda t=text: self.activity_label.config(text=t)
        )

    def finish_job(self, error, message):
        self.busy = False
        self.progress.stop()

        if error:
            self.state_label.config(
                text="● HATA", fg=RED
            )
            self.activity_label.config(text=error)
            messagebox.showerror("Agent hatası", error)
        else:
            self.state_label.config(
                text="● BEKLEMEDE", fg="#667085"
            )
            self.activity_label.config(text=message)

        self.refresh()

    def repair_drafts(self):
        if not self.open_job(
            "Eksik yorum taslakları kontrol ediliyor..."
        ):
            return

        def worker():
            error = None
            created = 0

            try:
                with self.connect() as db:
                    rows = db.execute("""
                        SELECT v.video_id
                        FROM videos v
                        JOIN langgraph_results r
                            ON v.video_id = r.video_id
                        LEFT JOIN comment_drafts c
                            ON v.video_id = c.video_id
                        WHERE r.decision = 'relevant'
                          AND c.video_id IS NULL
                        ORDER BY v.discovered_at DESC
                    """).fetchall()

                    total = len(rows)

                    for index, (video_id,) in enumerate(
                        rows, start=1
                    ):
                        self.set_activity(
                            f"Taslak oluşturuluyor: {index}/{total}"
                        )

                        used = {
                            item[0] for item in db.execute("""
                                SELECT comment
                                FROM comment_drafts
                            """).fetchall()
                        }

                        candidates = [
                            praise for praise in PRAISES
                            if f"{SIGNATURE}\n{praise}" not in used
                        ]

                        praise = random.choice(
                            candidates if candidates else PRAISES
                        )

                        comment = f"{SIGNATURE}\n{praise}"

                        cursor = db.execute("""
                            INSERT OR IGNORE INTO comment_drafts
                            (video_id, comment, review_status, created_at)
                            VALUES (?, ?, 'pending_review', CURRENT_TIMESTAMP)
                        """, (video_id, comment))

                        created += cursor.rowcount

                    db.commit()

            except Exception as exc:
                error = str(exc)

            self.root.after(
                0,
                lambda e=error, n=created: self.finish_job(
                    e, f"{n} eksik yorum taslağı oluşturuldu."
                )
            )

        threading.Thread(
            target=worker, daemon=True
        ).start()

    def start_analysis(self, search_first):
        if not self.open_job(
            "Video arama ve analiz başlatıldı..."
        ):
            return

        def worker():
            error = None
            processed = 0

            try:
                if search_first:
                    self.set_activity(
                        "YouTube'da yeni videolar aranıyor..."
                    )
                    search_youtube()

                with self.connect() as db:
                    videos = db.execute("""
                        SELECT v.video_id, v.title
                        FROM videos v
                        LEFT JOIN langgraph_results r
                            ON v.video_id = r.video_id
                        WHERE r.video_id IS NULL
                        ORDER BY v.discovered_at DESC
                    """).fetchall()

                total = len(videos)

                for index, (video_id, title) in enumerate(
                    videos, start=1
                ):
                    self.set_activity(
                        f"Analiz: {index}/{total} - {title}"
                    )

                    description = get_video_description(video_id)

                    result = agent.invoke({
                        "title": title,
                        "description": description[:3000],
                        "decision": "",
                        "reason": "",
                        "comment_draft": ""
                    })

                    decision = result["decision"]
                    reason = result["reason"]
                    comment = result.get(
                        "comment_draft", ""
                    ).strip()

                    if decision not in (
                        "relevant", "irrelevant", "uncertain"
                    ):
                        raise ValueError("Invalid AI decision")

                    if decision == "relevant" and not comment:
                        raise ValueError("Empty comment draft")

                    with self.connect() as db:
                        db.execute("""
                            INSERT OR IGNORE INTO langgraph_results
                            (video_id, decision, reason)
                            VALUES (?, ?, ?)
                        """, (video_id, decision, reason))

                        db.execute("""
                            UPDATE videos SET status = ?
                            WHERE video_id = ?
                        """, (decision, video_id))

                        if decision == "relevant":
                            db.execute("""
                                INSERT OR IGNORE INTO comment_drafts
                                (video_id, comment, review_status, created_at)
                                VALUES (?, ?, 'pending_review', CURRENT_TIMESTAMP)
                            """, (video_id, comment))

                    processed += 1

            except Exception as exc:
                error = str(exc)

            self.root.after(
                0,
                lambda e=error, n=processed: self.finish_job(
                    e, f"{n} video analiz edildi."
                )
            )

        threading.Thread(
            target=worker, daemon=True
        ).start()

    def post(self):
        row = self.rows.get(self.current_id)

        if not row or row[4] != "approved" or self.busy:
            return

        video_id = self.current_id
        title = row[1]
        comment = row[3]

        if already_posted(video_id):
            messagebox.showwarning(
                "Uyarı",
                "Bu videoya daha önce yorum gönderilmiş."
            )
            return

        confirmed = messagebox.askyesno(
            "YOUTUBE GÖNDERİM ONAYI",
            f"Video:\n{title}\n\n"
            f"Yorum:\n{comment}\n\n"
            "Bu yorum ozi zwei hesabından yayımlansın mı?"
        )

        if not confirmed:
            return

        with self.connect() as db:
            latest = db.execute("""
                SELECT comment, review_status
                FROM comment_drafts
                WHERE video_id = ?
            """, (video_id,)).fetchone()

        if latest != (comment, "approved"):
            messagebox.showwarning(
                "Uyarı",
                "Yorum değişmiş. Yeniden kontrol et."
            )
            self.refresh()
            return

        if not self.open_job(
            "Yorum YouTube'a gönderiliyor..."
        ):
            return

        def worker():
            error = None

            try:
                if already_posted(video_id):
                    raise RuntimeError(
                        "Bu video zaten gönderilmiş."
                    )

                comment_id = post_one_comment(
                    video_id, comment
                )

                record_success(
                    video_id, comment_id
                )

            except Exception as exc:
                error = str(exc)

            self.root.after(
                0,
                lambda e=error: self.finish_post(e)
            )

        threading.Thread(
            target=worker, daemon=True
        ).start()

    def finish_post(self, error):
        self.busy = False
        self.progress.stop()

        if error:
            self.state_label.config(
                text="● HATA", fg=RED
            )
            messagebox.showerror(
                "Gönderim hatası",
                error
                + "\n\nTekrar denemeden önce "
                  "YouTube'da yorumu kontrol et."
            )
        else:
            self.state_label.config(
                text="● BEKLEMEDE", fg="#667085"
            )
            self.activity_label.config(
                text="Yorum başarıyla gönderildi."
            )
            messagebox.showinfo(
                "Başarılı",
                "Yorum YouTube'a gönderildi ve kaydedildi."
            )

        self.refresh()


def main():
    root = tk.Tk()
    ArdaDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
