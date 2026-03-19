import numpy as np
import json,os,pickle
import logging
log=logging.getLogger(__name__)

# ============================================================
# SIMPLIFIED TRANSFORMER MODEL
# Captures long-range temporal patterns in price data
# ============================================================

class AttentionLayer:
    """
    Self-attention mechanism:
    Learns which past candles matter most for prediction
    """
    def __init__(self,d_model=32,n_heads=4):
        self.d_model=d_model
        self.n_heads=n_heads
        self.d_k=d_model//n_heads
        np.random.seed(42)
        scale=np.sqrt(2.0/d_model)
        self.Wq=np.random.randn(d_model,d_model)*scale
        self.Wk=np.random.randn(d_model,d_model)*scale
        self.Wv=np.random.randn(d_model,d_model)*scale
        self.Wo=np.random.randn(d_model,d_model)*scale

    def forward(self,x):
        """x shape: (seq_len, d_model)"""
        Q=x@self.Wq
        K=x@self.Wk
        V=x@self.Wv
        # Attention scores
        scores=Q@K.T/np.sqrt(self.d_k)
        # Softmax
        scores=scores-scores.max(axis=-1,keepdims=True)
        attn=np.exp(scores)
        attn=attn/attn.sum(axis=-1,keepdims=True)
        # Output
        out=(attn@V)@self.Wo
        return out,attn

class MarketTransformer:
    """
    Transformer for market prediction:
    Input: Last 30 candles (30 × features)
    Output: Probability of UP/DOWN/FLAT
    """
    def __init__(self,n_features=8,seq_len=30,d_model=32):
        self.n_features=n_features
        self.seq_len=seq_len
        self.d_model=d_model
        np.random.seed(42)
        # Input projection
        self.input_proj=np.random.randn(n_features,d_model)*0.1
        # Attention
        self.attention=AttentionLayer(d_model)
        # Output layers
        self.W1=np.random.randn(d_model,16)*0.1
        self.W2=np.random.randn(16,3)*0.1
        self.b1=np.zeros(16)
        self.b2=np.zeros(3)
        # Weights for training
        self.learning_rate=0.001
        self.trained=False

    def _extract_features(self,df5):
        """Extract 8 features per candle"""
        features=[]
        c=df5['close'].values
        h=df5['high'].values
        l=df5['low'].values
        v=df5['volume'].values

        for i in range(1,len(df5)):
            ret=(c[i]-c[i-1])/c[i-1] if c[i-1]>0 else 0
            hl=(h[i]-l[i])/c[i] if c[i]>0 else 0
            vol_r=v[i]/np.mean(v[max(0,i-20):i]) if i>0 else 1
            # RSI approximation
            gains=np.maximum(np.diff(c[max(0,i-14):i+1]),0)
            losses=np.maximum(-np.diff(c[max(0,i-14):i+1]),0)
            avg_g=np.mean(gains) if len(gains)>0 else 0.001
            avg_l=np.mean(losses) if len(losses)>0 else 0.001
            rsi=100-(100/(1+avg_g/avg_l)) if avg_l>0 else 50

            features.append([
                np.clip(ret,-0.05,0.05),
                np.clip(hl,0,0.05),
                np.clip(vol_r/3,0,1),
                rsi/100,
                (c[i]-np.mean(c[max(0,i-20):i]))/c[i] if i>0 else 0,
                1 if c[i]>np.mean(c[max(0,i-5):i]) else -1,
                np.clip(abs(ret)*100,0,1),
                1 if vol_r>1.5 else 0
            ])

        if len(features)<self.seq_len:
            pad=[[0]*self.n_features]*(self.seq_len-len(features))
            features=pad+features
        return np.array(features[-self.seq_len:],dtype=np.float32)

    def _forward(self,seq):
        """Forward pass"""
        # Project input
        x=seq@self.input_proj  # (seq_len, d_model)
        # Attention
        x,_=self.attention.forward(x)
        # Pool (mean)
        x=x.mean(axis=0)  # (d_model,)
        # Dense layers
        h1=np.maximum(0,x@self.W1+self.b1)  # ReLU
        out=h1@self.W2+self.b2
        # Softmax
        out=out-out.max()
        probs=np.exp(out)
        probs=probs/probs.sum()
        return probs

    def predict(self,df5):
        """Predict market direction"""
        try:
            seq=self._extract_features(df5)
            probs=self._forward(seq)
            # 0=DOWN, 1=UP, 2=FLAT
            return probs
        except:return np.array([0.33,0.33,0.34])

    def train(self,X,y,epochs=10):
        """Train on historical data"""
        print(f'[TRANSFORMER] Training on {len(X)} samples...')
        losses=[]
        for ep in range(epochs):
            total_loss=0
            indices=np.random.permutation(len(X))
            for idx in indices:
                seq=X[idx]
                label=y[idx]
                # Forward
                probs=self._forward(seq)
                # Cross entropy loss
                loss=-np.log(probs[label]+1e-8)
                total_loss+=loss
                # Backward (simplified gradient)
                grad=probs.copy()
                grad[label]-=1
                # Update output layer
                h1=np.maximum(0,seq.mean(axis=0)@self.W1+self.b1)
                self.W2-=self.learning_rate*np.outer(h1,grad)
                self.b2-=self.learning_rate*grad
            avg_loss=total_loss/len(X)
            losses.append(avg_loss)
            if ep%5==0:
                print(f'[TRANSFORMER] Epoch {ep}: loss={avg_loss:.4f}')
        self.trained=True
        return losses

def train_transformer(symbol,df,lookback_days=30):
    """Train transformer on historical candle data"""
    print(f'[TRANSFORMER] Training {symbol}...')
    transformer=MarketTransformer()

    X=[];y=[]
    step=5

    for i in range(60,len(df)-10,step):
        df5=df.iloc[i-60:i].copy()
        # Label: next 10 candles direction
        future=df.iloc[i:i+10]
        if len(future)<10:continue
        future_ret=(float(future['close'].iloc[-1])-
                    float(df5['close'].iloc[-1]))/float(df5['close'].iloc[-1])

        if future_ret>0.003:label=1   # UP
        elif future_ret<-0.003:label=0  # DOWN
        else:label=2                    # FLAT

        seq=transformer._extract_features(df5)
        X.append(seq)
        y.append(label)

    if len(X)<100:
        print(f'[TRANSFORMER] {symbol}: Not enough data')
        return None

    X=np.array(X);y=np.array(y)
    # Balance classes
    unique,counts=np.unique(y,return_counts=True)
    print(f'[TRANSFORMER] {symbol}: {dict(zip(unique,counts))}')

    # Train
    transformer.train(X,y,epochs=20)

    # Evaluate
    correct=sum(1 for i in range(len(X))
                if np.argmax(transformer._forward(X[i]))==y[i])
    acc=correct/len(X)*100
    print(f'[TRANSFORMER] ✅ {symbol}: Acc={acc:.1f}%')

    # Save
    os.makedirs('ml_models',exist_ok=True)
    pickle.dump(transformer,
                open(f'ml_models/{symbol}_v31_transformer.pkl','wb'))
    return transformer

def get_transformer_signal(symbol,df5):
    """
    Get transformer prediction:
    Returns: direction(0=down,1=up,2=flat), confidence
    """
    try:
        tf_file=f'ml_models/{symbol}_v31_transformer.pkl'
        if not os.path.exists(tf_file):return 2,0.33

        transformer=pickle.load(open(tf_file,'rb'))
        probs=transformer.predict(df5)
        direction=int(np.argmax(probs))
        confidence=float(probs[direction])
        return direction,confidence

    except Exception as e:
        log.error(f'[TRANSFORMER] Error {symbol}: {e}')
        return 2,0.33
