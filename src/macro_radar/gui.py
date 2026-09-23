from __future__ import annotations
import json
import logging
import os
import queue
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import Tk, StringVar, BooleanVar, Toplevel, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from .config import load_sources, load_yaml
from .pipeline import run_pipeline
from .store import EventStore
from .translation import Translator, TYPES, LEVELS, SOURCES

def app_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]

def resource_root():
    return Path(getattr(sys, '_MEIPASS', app_root()))

class RadarApp:
    def __init__(self, root):
        self.root = root
        root.title('宏观与地缘事件雷达 · 1.4')
        root.geometry('1280x850')
        root.minsize(1000, 720)
        root.configure(background='#f4f6f9')
        self.data = app_root() / 'data'
        self.data.mkdir(exist_ok=True)
        self.log_dir = app_root() / 'logs'
        self.log_dir.mkdir(exist_ok=True)
        logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(self.log_dir/'radar-gui.log', encoding='utf-8')], format='%(asctime)s %(levelname)s %(message)s')
        logging.getLogger('httpx').setLevel(logging.WARNING)
        root.report_callback_exception = self.callback_error
        self.translator = Translator(self.data/'translations.db')
        self.messages = queue.Queue()
        self.translation_jobs = queue.PriorityQueue()
        self.pending = set()
        self.job_sequence = 0
        self.errors = {}
        self.rows = []
        self.health = []
        self.running = False
        self.closed = False
        self.auto = BooleanVar(value=True)
        self.rules = load_yaml(resource_root()/'config'/'rules.yaml')
        self.status = StringVar(value='准备就绪 · 打开事件后自动翻译详情')
        self.freshness = StringVar()
        self.filter = StringVar(value='全部类型')
        self.score_filter = StringVar(value='重要事件（50+）')
        self.search = StringVar()
        self._style()
        self._ui()
        self.reload()
        health_path = self.data/'source-health.json'
        if health_path.exists():
            try:
                self.health = json.loads(health_path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                pass
        threading.Thread(target=self._translation_worker, daemon=True).start()
        root.after(100, self._drain)
        root.after(1200, lambda: self.fetch(force=True))
        root.after(60000, self._auto_tick)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def _style(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('.', font=('Microsoft YaHei UI', 10), background='#f4f6f9', foreground='#233044')
        s.configure('TFrame', background='#f4f6f9')
        s.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'), foreground='#142d43')
        s.configure('Muted.TLabel', foreground='#617084')
        s.configure('TButton', padding=(12, 8), background='#ffffff', borderwidth=0)
        s.configure('Primary.TButton', background='#147d83', foreground='white')
        s.map('Primary.TButton', background=[('active', '#11666b'), ('disabled', '#a5b7bd')])
        s.configure('Treeview', background='white', fieldbackground='white', rowheight=38, borderwidth=0)
        s.configure('Treeview.Heading', background='#e9eef3', padding=(8, 10), font=('Microsoft YaHei UI', 10, 'bold'))
        s.map('Treeview', background=[('selected', '#d9eeef')], foreground=[('selected', '#143c43')])

    def _ui(self):
        header = ttk.Frame(self.root, padding=(24, 20, 24, 10))
        header.pack(fill='x')
        ttk.Label(header, text='宏观与地缘事件雷达', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='官方消息  /  公开高可信快讯  /  重要事件优先  /  中文阅读  /  原文可追溯', style='Muted.TLabel').pack(anchor='w', pady=(6, 0))
        ttk.Label(header, text='筛选口径：仅保留可能影响利率、汇率、债券、股指、能源、航运的事件；排除一般战争、人权、援助与和平建设信息', wraplength=1150, style='Muted.TLabel').pack(anchor='w', pady=(12, 0))
        ttk.Label(header, text='事件类型：央行决议 · 重大宏观数据 · 制裁行动 · 出口管制 · 关税与贸易 · 市场相关地缘冲突 · 核风险 · 能源供应 · 市场相关讲话 · 重大政策', wraplength=1150, style='Muted.TLabel').pack(anchor='w', pady=(5, 0))
        toolbar = ttk.Frame(self.root, padding=(24, 4, 24, 8))
        toolbar.pack(fill='x')
        self.fetch_button = ttk.Button(toolbar, text='抓取最新事件', style='Primary.TButton', command=self.fetch)
        self.fetch_button.pack(side='left')
        ttk.Button(toolbar, text='信源状态', command=self.show_health).pack(side='left', padx=8)
        ttk.Checkbutton(toolbar, text='每 1 分钟自动刷新', variable=self.auto).pack(side='left', padx=12)
        ttk.Label(toolbar, text='重要性', style='Muted.TLabel').pack(side='right', padx=(12, 5))
        score_combo = ttk.Combobox(toolbar, textvariable=self.score_filter, values=['重要事件（50+）', '高重要（75+）', '紧急（90+）', '全部'], state='readonly', width=14)
        score_combo.pack(side='right')
        score_combo.bind('<<ComboboxSelected>>', lambda e:self.render())
        combo = ttk.Combobox(toolbar, textvariable=self.filter, values=['全部类型']+list(TYPES.values()), state='readonly', width=13)
        combo.pack(side='right')
        combo.bind('<<ComboboxSelected>>', lambda e:self.render())
        search = ttk.Entry(toolbar, textvariable=self.search, width=25)
        search.pack(side='right', padx=8)
        self.search.trace_add('write', lambda *a:self.render())
        ttk.Label(toolbar, text='搜索', style='Muted.TLabel').pack(side='right')
        ttk.Label(self.root, textvariable=self.freshness, style='Muted.TLabel', padding=(24, 5), wraplength=1200).pack(fill='x')
        ttk.Label(self.root, textvariable=self.status, padding=(24, 5), wraplength=1200).pack(fill='x')
        pane = ttk.PanedWindow(self.root, orient='vertical')
        pane.pack(fill='both', expand=True, padx=24, pady=(10, 20))
        frame = ttk.Frame(pane)
        pane.add(frame, weight=3)
        cols = ('score','type','title','source','date')
        self.tree = ttk.Treeview(frame, columns=cols, show='headings', selectmode='browse')
        for col, label, width in zip(cols, ['重要性','事件类型','中文标题 / 原文','来源','发布时间（本地）'], [85,110,570,155,165]):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=60, stretch=col=='title')
        self.tree.tag_configure('odd', background='#f7f9fb')
        self.tree.tag_configure('high', foreground='#a05a18')
        self.tree.tag_configure('critical', foreground='#b73540')
        ys = ttk.Scrollbar(frame, command=self.tree.yview)
        xs = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        xs.pack(side='bottom', fill='x')
        ys.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.show_selected)
        detail_frame = ttk.Frame(pane, padding=(0, 12, 0, 0))
        pane.add(detail_frame, weight=2)
        bar = ttk.Frame(detail_frame)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='事件详情 · 中英对照', font=('Microsoft YaHei UI', 12, 'bold')).pack(side='left')
        ttk.Button(bar, text='打开原文', command=self.open_original).pack(side='right')
        ttk.Button(bar, text='重新翻译', command=self.retry_translation).pack(side='right', padx=8)
        self.detail = ScrolledText(detail_frame, height=11, wrap='word', font=('Microsoft YaHei UI', 11), relief='flat', borderwidth=0, padx=16, pady=12, background='white', foreground='#233044')
        self.detail.pack(fill='both', expand=True)
        self.detail.insert('1.0', '选择一条消息，查看中文译文、原始摘要与原文链接。\n\n在线翻译：Google Translate 公共接口，MyMemory 备用；无需会员。仅发送公开标题和摘要，译文保存在本机。免费服务受限时可稍后重试。')
        self.detail.configure(state='disabled')

    def reload(self):
        store = EventStore(str(self.data/'events.db'))
        try:
            store.refresh_market_relevance(self.rules)
            self.rows = store.latest(500)
        finally:
            store.close()
        for row in self.rows:
            row['title_zh'] = self.translator.cached(row['title'])
        self.render()
        # Translate the newest page first; other titles are translated on selection.
        for row in self.rows[:20]:
            self.request_translation(row['title'], 10)

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().strip().lower()
        shown = 0
        min_score = {'重要事件（50+）': 50, '高重要（75+）': 75, '紧急（90+）': 90}.get(self.score_filter.get(), 0)
        for row in self.rows:
            label = TYPES.get(row['event_type'], '其他动态')
            title = row.get('title_zh') or row['title']
            if row['importance'] < min_score:
                continue
            if self.filter.get() not in ('全部类型', label):
                continue
            if query and query not in (title+' '+row['title']+' '+row.get('source_name','')).lower():
                continue
            self.tree.insert('', 'end', iid=row['event_id'], values=(f"{row['importance']} · {LEVELS.get(row['severity'], row['severity'])}", label, title, SOURCES.get(row.get('source_id'), row.get('source_name') or '官方来源'), self.display_time(row['published_at'])), tags=(('odd' if shown%2 else 'even'), row['severity']))
            shown += 1
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        latest = max((r['published_at'] for r in self.rows), default='')
        self.freshness.set(f'显示 {shown} / {len(self.rows)} 条  ·  库内最新发布：{self.display_time(latest) or "暂无"}  ·  发布时间与抓取时间不同；查看“信源状态”确认源站是否更新。')

    @staticmethod
    def display_time(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime('%m-%d %H:%M')
        except (ValueError, TypeError):
            return value or ''

    def selected(self):
        ids = self.tree.selection()
        return next((r for r in self.rows if ids and r['event_id']==ids[0]), None)

    def show_selected(self, event=None):
        row = self.selected()
        if not row:
            return
        for text in (row['title'], row['original_summary']):
            self.request_translation(text, 0)
        title = self.translator.cached(row['title']) or self.errors.get(row['title'], '正在翻译标题…')
        summary = self.translator.cached(row['original_summary']) if row['original_summary'] else '信源未提供摘要，请打开原文查看。'
        summary = summary or self.errors.get(row['original_summary'], '正在翻译摘要…')
        text = f"{title}\n\n中文摘要（机器翻译）\n{summary}\n\n事件类型：{TYPES.get(row['event_type'], '其他动态')}  ·  重要性：{row['importance']} / 100（{LEVELS.get(row['severity'])}）\n相关实体：{'、'.join(json.loads(row['entities_json'])) or '待识别'}\n潜在影响资产：{'、'.join(json.loads(row['assets_json'])) or '待评估'}（关联提示，不代表涨跌方向）\n发布时间：{row['published_at']}\n首次抓取：{row['fetched_at']}\n\n原始标题\n{row['title']}\n\n原始摘要\n{row['original_summary'] or '无'}\n\n原文链接\n{row['canonical_url']}"
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text)
        self.detail.configure(state='disabled')

    def request_translation(self, text, priority):
        if not text or text in self.pending or text in self.errors or self.translator.cached(text) is not None:
            return
        self.pending.add(text)
        self.job_sequence += 1
        self.translation_jobs.put((priority, self.job_sequence, text))

    def _translation_worker(self):
        while not self.closed:
            try:
                _, _, text = self.translation_jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.messages.put(('translated', text, self.translator.translate(text)))
            except Exception:
                self.messages.put(('translation_error', text, '暂未翻译：网络或免费额度限制，可点击重新翻译。'))

    def retry_translation(self):
        row = self.selected()
        if row:
            for text in (row['title'], row['original_summary']):
                self.errors.pop(text, None)
            self.show_selected()

    def fetch(self, force=True):
        if self.running:
            return
        self.running = True
        self.fetch_button.configure(state='disabled', text='抓取中…')
        self.status.set('正在检查官方源；只保留有明确金融市场传导线索的事件，翻译会在后台逐条补齐。')
        threading.Thread(target=self._fetch_worker, args=(force,), daemon=True).start()

    def _fetch_worker(self, force=True):
        try:
            config = resource_root()/'config'
            store = EventStore(str(self.data/'events.db'))
            try:
                sources = load_sources(config/'sources.yaml')
                previous = {}
                health_path = self.data/'source-health.json'
                if health_path.exists():
                    try:
                        previous = {row.get('source_id') or row.get('url'): row for row in json.loads(health_path.read_text(encoding='utf-8'))}
                        previous = {source.id: previous.get(source.id) or previous.get(source.url) or {} for source in sources}
                    except (ValueError, OSError):
                        previous = {}
                stats, _ = run_pipeline(sources, load_yaml(config/'rules.yaml'), store, limit=100, previous_health=previous, force=force)
            finally:
                store.close()
            (self.data/'source-health.json').write_text(json.dumps(stats.health, ensure_ascii=False, indent=2), encoding='utf-8')
            self.messages.put(('fetched', stats))
        except Exception as exc:
            logging.exception('Fetch failed')
            self.messages.put(('error', str(exc)))

    def _drain(self):
        try:
            for _ in range(30):
                try:
                    msg = self.messages.get_nowait()
                except queue.Empty:
                    break
                if msg[0] in ('translated', 'translation_error'):
                    self.pending.discard(msg[1])
                    if msg[0]=='translated':
                        for row in self.rows:
                            if row['title']==msg[1]:
                                row['title_zh']=msg[2]
                                if self.tree.exists(row['event_id']):
                                    self.tree.set(row['event_id'], 'title', msg[2])
                    else:
                        self.errors[msg[1]]=msg[2]
                    row=self.selected()
                    if row and msg[1] in (row['title'], row['original_summary']):
                        self.show_selected()
                elif msg[0]=='fetched':
                    stats=msg[1]
                    self.running=False
                    self.fetch_button.configure(state='normal', text='抓取最新事件')
                    self.health=stats.health
                    self.reload()
                    accepted = stats.fetched - stats.filtered - stats.scheduled
                    self.status.set(f'检查完成 {datetime.now():%H:%M:%S} · 源 {len(stats.health)} 个（成功 {stats.sources_ok} / 失败 {stats.sources_failed} / 等待 {stats.sources_skipped}）· 本轮抓到 {stats.fetched} · 市场保留 {accepted} · 未来日程 {stats.scheduled} · 排除 {stats.filtered} · 新入库 {stats.inserted} · 已在库 {stats.duplicates}')
                elif msg[0]=='error':
                    self.running=False
                    self.fetch_button.configure(state='normal', text='抓取最新事件')
                    self.status.set('抓取失败：'+msg[1])
        finally:
            if not self.closed:
                self.root.after(100, self._drain)

    def show_health(self):
        win=Toplevel(self.root)
        win.title('信源状态 · 检查时间与发布时间')
        win.geometry('950x480')
        box=ScrolledText(win, wrap='word', font=('Microsoft YaHei UI',11), padx=16, pady=16)
        box.pack(fill='both',expand=True)
        box.insert('end', '官方源按发布节奏更新，不保证每小时都有新闻。这里显示的是本轮抓到的原始条目；进入主列表前还会经过市场影响筛选。成功但最新时间较旧，表示本轮返回的源内容较旧；也可能存在源端缓存或发布延迟。\n\n')
        for h in self.health:
            error = f"\n原因：{h.get('error')}" if h.get('error') else ''
            box.insert('end', f"{h['name']}\n{h['state']} · 本轮条目 {h['count']} · 检查 {self.display_time(h['checked'])} · 最新发布 {self.display_time(h['latest']) or '未知'}{error}\n{h['url']}\n\n")
        if not self.health:
            box.insert('end', '尚未检查，请点击抓取最新事件。')
        box.configure(state='disabled')

    def open_original(self):
        row=self.selected()
        if row and row['canonical_url'].startswith(('https://','http://')):
            webbrowser.open(row['canonical_url'])

    def callback_error(self, kind, value, tb):
        logging.error('UI error', exc_info=(kind, value, tb))
        messagebox.showerror('界面错误', str(value))

    def _auto_tick(self):
        if self.auto.get():
            self.fetch(force=False)
        if not self.closed:
            self.root.after(60000, self._auto_tick)

    def close(self):
        self.closed=True
        self.root.destroy()

def main():
    root=Tk()
    app=RadarApp(root)
    if '--verify' in sys.argv:
        # Exercise the actual frozen GUI, fetch, translation and selection path.
        start=datetime.now()
        app.fetch()
        def verify():
            if app.running and (datetime.now()-start).total_seconds()<180:
                root.after(500, verify)
                return
            ids=app.tree.get_children()
            if ids:
                app.tree.selection_set(ids[0])
                app.show_selected()
            report={'rows':len(ids), 'health':app.health, 'status':app.status.get(), 'translated_titles':sum(bool(r.get('title_zh')) for r in app.rows), 'detail_rendered':bool(app.detail.get('1.0','end').strip())}
            (app.data/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            app.close()
        root.after(20000, verify)
    root.mainloop()

if __name__=='__main__':
    main()
