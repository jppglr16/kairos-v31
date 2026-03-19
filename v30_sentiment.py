import requests
from bs4 import BeautifulSoup
from datetime import datetime

NEGATIVE_WORDS = ['crash','fall','drop','loss','weak','down','bear','sell','fear','risk','war','crisis','inflation','rate hike']
POSITIVE_WORDS = ['rally','rise','gain','strong','up','bull','buy','growth','profit','recovery','boost','surge']

def get_market_news():
    try:
        url = 'https://feeds.finance.yahoo.com/rss/2.0/headline?s=^NSEI&region=IN&lang=en-IN'
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, 'xml')
        items = soup.find_all('item')[:10]
        headlines = [item.find('title').text.lower() for item in items]
        return headlines
    except Exception as e:
        print(f'[SENTIMENT] News error: {e}')
        return []

def get_sentiment_score():
    try:
        headlines = get_market_news()
        if not headlines: return 0
        pos = sum(1 for h in headlines for w in POSITIVE_WORDS if w in h)
        neg = sum(1 for h in headlines for w in NEGATIVE_WORDS if w in h)
        total = pos + neg
        if total == 0: return 0
        score = (pos - neg) / total
        print(f'[SENTIMENT] +{pos} -{neg} = {score:.2f}')
        return score
    except Exception as e:
        print(f'[SENTIMENT] Error: {e}')
        return 0

def get_sentiment_bias():
    score = get_sentiment_score()
    if score > 0.3: return 'BULLISH'
    elif score < -0.3: return 'BEARISH'
    return 'NEUTRAL'
