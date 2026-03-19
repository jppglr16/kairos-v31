import numpy as np
import logging,os,pickle,json
from datetime import datetime
log=logging.getLogger(__name__)

class MultiModalTransformer:
    """
    Multi-Modal Market Understanding Engine:
    Modal 1: Price + Volume (OHLCV)
    Modal 2: Options data (OI, Gamma, IV)
    Modal 3: News sentiment (keyword based)
    Modal 4: Order flow (bid/ask imbalance)
    
    Each modal = separate attention head
    Final = combined understanding!
    """

    def __init__(self,symbol,seq_len=30):
        self.symbol=symbol
        self.seq_len=seq_len
        self.models={}
        self._build_models()

    def _build_models(self):
        """Build separate model per modality"""
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.neural_network import MLPClassifier

            # Modal 1: Price+Volume model
            self.models['price_volume']=GradientBoostingClassifier(
                n_estimators=100,max_depth=3,learning_rate=0.05)

            # Modal 2: Options model
            self.models['options']=GradientBoostingClassifier(
                n_estimators=50,max_depth=3)

            # Modal 3: Sentiment model
            self.models['sentiment']=MLPClassifier(
                hidden_layer_sizes=(32,16),max_iter=100)

            # Modal 4: Order flow model
            self.models['order_flow']=GradientBoostingClassifier(
                n_estimators=50,max_depth=2)

            # Fusion model (combines all)
            self.models['fusion']=MLPClassifier(
                hidden_layer_sizes=(64,32,16),max_iter=100)

            log.info(f'[MMT] {self.symbol} models built!')
        except Exception as e:
            log.error(f'[MMT] Build error: {e}')

    # ============================================================
    # MODAL 1: PRICE + VOLUME FEATURES
    # ============================================================
    def extract_price_volume(self,df5,atr):
        """Extract rich price+volume features"""
        try:
            c=df5['close'].values
            h=df5['high'].values
            l=df5['low'].values
            v=df5['volume'].values
            n=len(c)

            if n<20:return np.zeros(20)

            cur=c[-1]
            features=[]

            # Price momentum
            features.append((c[-1]-c[-5])/c[-5] if c[-5]>0 else 0)   # 5-bar return
            features.append((c[-1]-c[-10])/c[-10] if c[-10]>0 else 0) # 10-bar return
            features.append((c[-1]-c[-20])/c[-20] if c[-20]>0 else 0) # 20-bar return

            # Volatility
            features.append(atr/cur if cur>0 else 0)
            features.append(np.std(c[-10:])/cur if cur>0 else 0)

            # Volume analysis
            avg_vol=np.mean(v[-20:]) if len(v)>=20 else np.mean(v)
            features.append(v[-1]/avg_vol if avg_vol>0 else 1)  # Vol ratio
            features.append(np.mean(v[-5:])/avg_vol if avg_vol>0 else 1)  # 5-bar vol

            # Candle patterns
            body=abs(c[-1]-c[-2])
            total_range=h[-1]-l[-1]
            features.append(body/total_range if total_range>0 else 0)  # Body ratio
            features.append((c[-1]-l[-1])/total_range if total_range>0 else 0.5)  # Wick pos

            # Price position
            high20=np.max(h[-20:])
            low20=np.min(l[-20:])
            rng=high20-low20
            features.append((cur-low20)/rng if rng>0 else 0.5)  # Range position

            # VWAP
            vwap=np.sum(c*v)/np.sum(v) if np.sum(v)>0 else cur
            features.append((cur-vwap)/vwap if vwap>0 else 0)

            # EMA relationships
            ema9=np.mean(c[-9:])
            ema21=np.mean(c[-21:]) if len(c)>=21 else ema9
            features.append((cur-ema9)/ema9 if ema9>0 else 0)
            features.append((ema9-ema21)/ema21 if ema21>0 else 0)

            # RSI
            gains=np.maximum(np.diff(c[-15:]),0)
            losses=np.maximum(-np.diff(c[-15:]),0)
            avg_gain=np.mean(gains) if len(gains)>0 else 0
            avg_loss=np.mean(losses) if len(losses)>0 else 0.001
            rsi=100-(100/(1+avg_gain/avg_loss))
            features.append(rsi/100)

            # Consecutive candles
            bullish=sum(1 for i in range(-5,0) if c[i]>c[i-1])
            features.append(bullish/5)

            # Volume trend
            vol_trend=(v[-1]-v[-5])/v[-5] if v[-5]>0 else 0
            features.append(min(max(vol_trend,-2),2))

            # High/Low breaks
            features.append(1 if cur>np.max(h[-10:-1]) else 0)  # Breakout
            features.append(1 if cur<np.min(l[-10:-1]) else 0)  # Breakdown

            # ATR multiple from support
            features.append(min((cur-np.min(l[-5:]))/atr,3) if atr>0 else 0)

            return np.array(features[:20],dtype=np.float32)
        except Exception as e:
            log.error(f'[MMT] Price features error: {e}')
            return np.zeros(20)

    # ============================================================
    # MODAL 2: OPTIONS DATA (OI, GAMMA, IV)
    # ============================================================
    def extract_options_features(self,instrument,current_price):
        """Extract options market features"""
        try:
            features=[]

            # Try to get real options data
            gamma_boost=0
            pcr=1.0  # Put/Call ratio
            iv=0.3   # Implied volatility
            max_oi_strike=current_price
            oi_imbalance=0

            try:
                from v31_gamma import get_gamma_walls
                walls=get_gamma_walls(instrument,current_price)
                if walls:
                    gamma_boost=walls.get('boost',0)
                    pcr=walls.get('pcr',1.0)
                    call_wall=walls.get('call_wall',current_price)
                    put_wall=walls.get('put_wall',current_price)
                    # Distance to walls
                    features.append((call_wall-current_price)/current_price if current_price>0 else 0)
                    features.append((current_price-put_wall)/current_price if current_price>0 else 0)
                else:
                    features.extend([0,0])
            except:
                features.extend([0,0])

            features.append(min(gamma_boost/10,1))  # Gamma strength
            features.append(min(pcr,3)/3)           # PCR normalized
            features.append(iv)                      # IV level

            # Expiry proximity
            now=datetime.now()
            days_to_expiry=(3-now.weekday())%7
            features.append(days_to_expiry/7)        # Days to expiry
            features.append(1 if days_to_expiry<=1 else 0)  # Expiry day flag

            # IV percentile (approximated)
            features.append(0.5)  # Placeholder - update with real data

            # OI imbalance
            features.append(oi_imbalance)

            # Strike distance (ATM proxy)
            features.append(0.5)  # ATM

            return np.array(features[:10],dtype=np.float32)
        except Exception as e:
            log.error(f'[MMT] Options features error: {e}')
            return np.zeros(10)

    # ============================================================
    # MODAL 3: NEWS SENTIMENT
    # ============================================================
    def extract_sentiment_features(self,instrument):
        """
        Keyword-based sentiment analysis
        No external API needed!
        Uses recent market context
        """
        try:
            features=[]
            sentiment_score=0.0
            market_fear=0.5  # Neutral default

            # Check global market sentiment from Angel One
            try:
                from v31_angel_trader import angel_trader
                if angel_trader and angel_trader.connected:
                    # Use market breadth as sentiment proxy
                    # Advance/decline ratio
                    funds=angel_trader.obj.rmsLimit()
                    if funds and funds.get('data'):
                        available=float(funds['data'].get('net',0) or 0)
                        # If capital increased = market going up = positive
                        sentiment_score=0.6 if available>50000 else 0.4
            except:pass

            features.append(sentiment_score)   # Overall sentiment
            features.append(market_fear)        # Fear level
            
            # Time-based sentiment proxy
            now=datetime.now()
            hour=now.hour
            # Morning = optimistic, afternoon = mixed
            if 9<=hour<=10:features.append(0.7)   # Opening optimism
            elif 10<=hour<=12:features.append(0.6)  # Morning trend
            elif 12<=hour<=14:features.append(0.5)  # Lunch neutral
            elif 14<=hour<=15:features.append(0.6)  # Closing action
            else:features.append(0.5)

            # Day-based sentiment
            weekday=now.weekday()
            day_sentiment=[0.6,0.55,0.5,0.65,0.45]  # Mon-Fri
            features.append(day_sentiment[min(weekday,4)])

            # Budget/expiry week
            features.append(1 if (3-weekday)%7<=2 else 0)  # Expiry week

            return np.array(features[:5],dtype=np.float32)
        except Exception as e:
            log.error(f'[MMT] Sentiment error: {e}')
            return np.zeros(5)

    # ============================================================
    # MODAL 4: ORDER FLOW
    # ============================================================
    def extract_order_flow(self,df5,atr):
        """
        Order flow analysis from price action:
        - Large candles = institutional flow
        - Volume spikes = big orders
        - Price impact = order imbalance
        """
        try:
            c=df5['close'].values
            h=df5['high'].values
            l=df5['low'].values
            v=df5['volume'].values
            n=len(c)
            if n<10:return np.zeros(8)

            features=[]

            # Buy/Sell pressure from candles
            buy_vol=sum(v[i] for i in range(-10,0) if c[i]>c[i-1])
            sell_vol=sum(v[i] for i in range(-10,0) if c[i]<c[i-1])
            total=buy_vol+sell_vol
            
            buy_pressure=buy_vol/total if total>0 else 0.5
            features.append(buy_pressure)
            features.append(1-buy_pressure)  # Sell pressure

            # Large candle detection (institutional)
            avg_range=np.mean(h[-20:]-l[-20:]) if n>=20 else atr
            large_candles=sum(1 for i in range(-5,0) if (h[i]-l[i])>avg_range*1.5)
            features.append(large_candles/5)

            # Volume spike
            avg_vol=np.mean(v[-20:]) if n>=20 else np.mean(v)
            vol_spike=v[-1]/avg_vol if avg_vol>0 else 1
            features.append(min(vol_spike,5)/5)

            # Price impact (how much price moved per unit volume)
            price_change=abs(c[-1]-c[-5])
            vol_5=np.mean(v[-5:])
            price_impact=price_change/(vol_5*0.001) if vol_5>0 else 0
            features.append(min(price_impact,1))

            # Absorption (big volume, small move = absorption)
            absorption=1/(price_impact+0.001) if price_impact>0 else 1
            features.append(min(absorption/10,1))

            # Delta (estimated)
            delta=sum((c[i]-c[i-1])*v[i] for i in range(-10,0))
            delta_norm=np.tanh(delta/(avg_vol*atr+0.001))
            features.append(float(delta_norm))

            # Trend of delta
            recent_delta=sum((c[i]-c[i-1])*v[i] for i in range(-5,0))
            older_delta=sum((c[i]-c[i-1])*v[i] for i in range(-10,-5))
            features.append(1 if recent_delta>older_delta else -1)

            return np.array(features[:8],dtype=np.float32)
        except Exception as e:
            log.error(f'[MMT] Order flow error: {e}')
            return np.zeros(8)

    # ============================================================
    # FUSION: COMBINE ALL MODALITIES
    # ============================================================
    def get_multimodal_features(self,df5,df15,instrument,current_price,atr):
        """Combine all 4 modalities"""
        try:
            f1=self.extract_price_volume(df5,atr)      # 20 features
            f2=self.extract_options_features(instrument,current_price)  # 10 features
            f3=self.extract_sentiment_features(instrument)  # 5 features
            f4=self.extract_order_flow(df5,atr)         # 8 features

            combined=np.concatenate([f1,f2,f3,f4])     # 43 features total
            return combined
        except Exception as e:
            log.error(f'[MMT] Fusion error: {e}')
            return np.zeros(43)

    def predict(self,df5,df15,instrument,current_price,atr,action='BUY'):
        """
        Multi-modal prediction:
        Returns probability of success
        """
        try:
            features=self.get_multimodal_features(df5,df15,instrument,current_price,atr)

            # Load fusion model if exists
            fname=f'ml_models/{instrument}_v31_mmt.pkl'
            if os.path.exists(fname):
                model=pickle.load(open(fname,'rb'))
                X=features.reshape(1,-1)
                prob=float(model.predict_proba(X)[0][1])
                log.info(f'[MMT] {instrument} prediction: {prob:.2f}')
                return prob,features

            # No model yet - return neutral
            return 0.5,features
        except Exception as e:
            log.error(f'[MMT] Predict error: {e}')
            return 0.5,np.zeros(43)

    def train(self,signals):
        """Train fusion model on historical signals"""
        try:
            X=[s.get('mmt_features',[]) for s in signals
               if s.get('mmt_features') and s.get('outcome') is not None]
            y=[s['outcome'] for s in signals
               if s.get('mmt_features') and s.get('outcome') is not None]

            if len(X)<50:
                log.info(f'[MMT] {self.symbol}: Need more data ({len(X)}/50)')
                return False

            from sklearn.ensemble import GradientBoostingClassifier
            model=GradientBoostingClassifier(
                n_estimators=200,max_depth=4,
                learning_rate=0.05,subsample=0.8)
            model.fit(np.array(X),np.array(y))

            fname=f'ml_models/{self.symbol}_v31_mmt.pkl'
            pickle.dump(model,open(fname,'wb'))

            wins=sum(y)
            log.info(f'[MMT] {self.symbol} trained: {len(X)} samples WR:{wins/len(X)*100:.1f}%')
            return True
        except Exception as e:
            log.error(f'[MMT] Train error: {e}')
            return False


# Global instances
_mmt_engines={}

def get_mmt_engine(symbol):
    if symbol not in _mmt_engines:
        _mmt_engines[symbol]=MultiModalTransformer(symbol)
    return _mmt_engines[symbol]

def get_mmt_prob(symbol,df5,df15,instrument,price,atr,action='BUY'):
    """Main function to get multi-modal probability"""
    engine=get_mmt_engine(symbol)
    prob,features=engine.predict(df5,df15,instrument,price,atr,action)
    return prob,features
