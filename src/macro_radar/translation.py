"""Public news translation with persistent cache and explicit failures."""
import html
import re
import sqlite3
import httpx

TYPES = {'rate_decision':'央行决议', 'sanctions':'制裁行动', 'export_control':'出口管制', 'tariff_trade':'关税与贸易', 'conflict':'市场相关地缘冲突', 'nuclear':'核风险', 'energy_supply':'能源供应', 'policy_speech':'市场相关讲话', 'major_policy':'重大政策', 'macro_data':'重大宏观数据', 'other':'其他动态'}
LEVELS = {'critical':'紧急', 'high':'高', 'medium':'中', 'low':'低'}
SOURCES = {'fed_monetary':'美联储 · 货币政策','fed_speeches':'美联储 · 讲话证词','fed_all_press':'美联储 · 全部公告','ecb_press':'欧洲央行','boj_whats_new':'日本央行','iaea_top_news':'国际原子能机构','un_peace':'联合国 · 和平与安全','eia_energy':'美国能源信息署','doe_energy_policy':'美国能源部','marketwatch_top':'MarketWatch · 公开快讯','cnbc_top':'CNBC · 公开快讯','cnbc_markets':'CNBC · 市场','cnbc_world':'CNBC · 世界','yahoo_finance_top':'Yahoo Finance · 市场头条','yahoo_finance_sp500':'Yahoo Finance · 标普500','yahoo_finance_wti':'Yahoo Finance · WTI原油','oilprice_main':'OilPrice · 能源','us_treasury_press':'美国财政部','ofac_actions':'OFAC 制裁','ustr_press':'美国贸易代表办公室','whitehouse_briefing':'白宫','pboc_news':'中国人民银行','china_mfa_news':'中国外交部','china_mofcom_news':'中国商务部','china_stats_news':'国家统计局','ec_commission_news':'欧盟委员会'}

class Translator:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS translations(text TEXT PRIMARY KEY, zh TEXT NOT NULL)')

    def cached(self, text):
        if not text:
            return ''
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT zh FROM translations WHERE text=?', (text,)).fetchone()
        return row[0] if row else None

    def translate(self, text):
        if not text:
            return ''
        cached = self.cached(text)
        if cached is not None:
            return cached
        # Respect the documented 500-byte request limit, without truncation.
        chunks, part = [], ''
        for char in text:
            if len((part + char).encode('utf-8')) > 450:
                chunks.append(part)
                part = ''
            part += char
        if part:
            chunks.append(part)
        result = []
        with httpx.Client(timeout=15) as client:
            for chunk in chunks:
                value = None
                errors = []
                try:
                    # Google Translate's public web endpoint requires no account
                    # or key. Results are cached locally to keep traffic small.
                    response = client.get('https://translate.googleapis.com/translate_a/single', params={'client':'gtx', 'sl':'auto', 'tl':'zh-CN', 'dt':'t', 'q':chunk})
                    response.raise_for_status()
                    data = response.json()
                    value = ''.join(part[0] for part in data[0] if part and part[0])
                except Exception as exc:
                    errors.append(exc)
                if not value:
                    try:
                        response = client.get('https://api.mymemory.translated.net/get', params={'q':chunk, 'langpair':'en|zh-CN'})
                        response.raise_for_status()
                        data = response.json()
                        if str(data.get('responseStatus')) != '200' or data.get('quotaFinished'):
                            raise RuntimeError('MyMemory 免费额度不足')
                        value = html.unescape(data['responseData']['translatedText'])
                    except Exception as exc:
                        errors.append(exc)
                if not value:
                    raise RuntimeError('免费翻译服务暂时不可用，请稍后重试') from errors[-1]
                if re.search('[A-Za-z]', chunk) and not re.search('[\u4e00-\u9fff]', value):
                    raise RuntimeError('翻译服务未返回中文，请稍后重试')
                result.append(value)
        zh = ''.join(result)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO translations VALUES (?,?)', (text, zh))
        return zh
