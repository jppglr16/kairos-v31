import json,os,pickle
import numpy as np
from datetime import datetime

class TradingEnvironment:
    def __init__(self,df,instrument,capital=50000):
        self.df=df
        self.instrument=instrument
        self.capital=capital
        self.current_capital=capital
        self.LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,
                  'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
        self.lot=self.LOT.get(instrument,25)
        self.reset()

    def reset(self):
        self.position=None
        self.entry_price=0
        self.current_capital=self.capital
        self.trades=[]
        self.step_idx=100
        return self.get_state()

    def get_state(self):
        try:
            df5=self.df.iloc[self.step_idx-60:self.step_idx]
            c=df5['close'].values
            h=df5['high'].values
            l=df5['low'].values
            v=df5['volume'].values
            # Normalize features
            price_norm=(c[-1]-c.min())/(c.max()-c.min()) if c.max()!=c.min() else 0.5
            rsi=self.calc_rsi(c)
            atr=(h-l)[-14:].mean()/c[-1]
            vol_ratio=v[-1]/v[-20:].mean() if v[-20:].mean()>0 else 1
            trend=(c[-1]-c[-20])/c[-20] if len(c)>20 else 0
            macd=self.calc_macd(c)
            position_val=1 if self.position=='BUY' else -1 if self.position=='SELL' else 0
            capital_ratio=self.current_capital/self.capital
            return np.array([
                price_norm,rsi/100,atr,
                min(vol_ratio,3)/3,trend,macd,
                position_val,capital_ratio
            ])
        except:
            return np.zeros(8)

    def calc_rsi(self,prices,period=14):
        try:
            deltas=np.diff(prices)
            gains=np.where(deltas>0,deltas,0)
            losses=np.where(deltas<0,-deltas,0)
            avg_gain=gains[-period:].mean()
            avg_loss=losses[-period:].mean()
            if avg_loss==0:return 100
            rs=avg_gain/avg_loss
            return 100-(100/(1+rs))
        except:return 50

    def calc_macd(self,prices):
        try:
            s=pd.Series(prices)
            import pandas as pd
            s=pd.Series(prices)
            ema12=s.ewm(span=12).mean().iloc[-1]
            ema26=s.ewm(span=26).mean().iloc[-1]
            return (ema12-ema26)/prices[-1]
        except:return 0

    def step(self,action):
        # Actions: 0=HOLD, 1=BUY, 2=SELL, 3=EXIT
        reward=0
        done=False
        self.step_idx+=1

        if self.step_idx>=len(self.df)-20:
            done=True
            if self.position:
                current=self.df['close'].iloc[self.step_idx]
                if self.position=='BUY':
                    pnl=(current-self.entry_price)*self.lot
                else:
                    pnl=(self.entry_price-current)*self.lot
                self.current_capital+=pnl
                reward=self.calc_reward(pnl)
            return self.get_state(),reward,done

        current_price=self.df['close'].iloc[self.step_idx]
        atr=(self.df['high'].iloc[max(0,self.step_idx-14):self.step_idx]-
             self.df['low'].iloc[max(0,self.step_idx-14):self.step_idx]).mean()
        sl=atr*1.5
        t2=atr*2.5

        if action==1 and not self.position:  # BUY
            self.position='BUY'
            self.entry_price=current_price
            reward=-0.1  # Small cost for entering
        elif action==2 and not self.position:  # SELL
            self.position='SELL'
            self.entry_price=current_price
            reward=-0.1
        elif action==3 and self.position:  # EXIT
            if self.position=='BUY':
                pnl=(current_price-self.entry_price)*self.lot
            else:
                pnl=(self.entry_price-current_price)*self.lot
            self.current_capital+=pnl-120
            reward=self.calc_reward(pnl)
            self.trades.append({'pnl':pnl,'action':self.position})
            self.position=None

        # Auto exit on SL/T2
        if self.position:
            if self.position=='BUY':
                if current_price<=self.entry_price-sl:
                    pnl=-sl*self.lot
                    self.current_capital+=pnl-120
                    reward=self.calc_reward(pnl)
                    self.trades.append({'pnl':pnl,'action':'BUY'})
                    self.position=None
                elif current_price>=self.entry_price+t2:
                    pnl=t2*self.lot
                    self.current_capital+=pnl-120
                    reward=self.calc_reward(pnl)
                    self.trades.append({'pnl':pnl,'action':'BUY'})
                    self.position=None
            else:
                if current_price>=self.entry_price+sl:
                    pnl=-sl*self.lot
                    self.current_capital+=pnl-120
                    reward=self.calc_reward(pnl)
                    self.trades.append({'pnl':pnl,'action':'SELL'})
                    self.position=None
                elif current_price<=self.entry_price-t2:
                    pnl=t2*self.lot
                    self.current_capital+=pnl-120
                    reward=self.calc_reward(pnl)
                    self.trades.append({'pnl':pnl,'action':'SELL'})
                    self.position=None

        return self.get_state(),reward,done

    def calc_reward(self,pnl):
        if pnl>5000:return 10
        elif pnl>2500:return 5
        elif pnl>0:return 2
        elif pnl>-1000:return -1
        elif pnl>-2500:return -3
        else:return -5

class DQNAgent:
    def __init__(self,state_size=8,action_size=4):
        self.state_size=state_size
        self.action_size=action_size
        self.epsilon=1.0
        self.epsilon_min=0.01
        self.epsilon_decay=0.995
        self.gamma=0.95
        self.lr=0.001
        self.memory=[]
        self.max_memory=10000
        self.q_table={}

    def get_state_key(self,state):
        return tuple(np.round(state,1))

    def get_q_values(self,state):
        key=self.get_state_key(state)
        if key not in self.q_table:
            self.q_table[key]=np.zeros(self.action_size)
        return self.q_table[key]

    def act(self,state):
        if np.random.random()<self.epsilon:
            return np.random.randint(self.action_size)
        return np.argmax(self.get_q_values(state))

    def remember(self,state,action,reward,next_state,done):
        self.memory.append((state,action,reward,next_state,done))
        if len(self.memory)>self.max_memory:
            self.memory.pop(0)

    def replay(self,batch_size=32):
        if len(self.memory)<batch_size:return
        indices=np.random.choice(len(self.memory),batch_size,replace=False)
        for idx in indices:
            state,action,reward,next_state,done=self.memory[idx]
            target=reward
            if not done:
                target=reward+self.gamma*np.max(self.get_q_values(next_state))
            key=self.get_state_key(state)
            if key not in self.q_table:
                self.q_table[key]=np.zeros(self.action_size)
            self.q_table[key][action]+=self.lr*(target-self.q_table[key][action])
        if self.epsilon>self.epsilon_min:
            self.epsilon*=self.epsilon_decay

    def save(self,instrument):
        os.makedirs('rl_models',exist_ok=True)
        pickle.dump({
            'q_table':self.q_table,
            'epsilon':self.epsilon,
            'instrument':instrument,
            'trained_on':str(datetime.now())
        },open(f'rl_models/{instrument}_dqn.pkl','wb'))
        print(f'[RL] Saved rl_models/{instrument}_dqn.pkl')

    def load(self,instrument):
        f=f'rl_models/{instrument}_dqn.pkl'
        if os.path.exists(f):
            data=pickle.load(open(f,'rb'))
            self.q_table=data['q_table']
            self.epsilon=max(0.1,data.get('epsilon',0.1))
            print(f'[RL] Loaded {instrument} model eps={self.epsilon:.3f}')
            return True
        return False

def train_rl_agent(instrument,episodes=50):
    import pandas as pd
    from v30_backtest import load_historical_data,candles_to_df

    print(f'\n[RL] Training {instrument} for {episodes} episodes...')
    agent=DQNAgent()

    all_candles=[]
    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        all_candles.extend(candles)

    if not all_candles:
        print(f'[RL] No data for {instrument}')
        return None

    df=candles_to_df(all_candles)
    if df is None:return None

    best_capital=0
    episode_results=[]

    for ep in range(episodes):
        env=TradingEnvironment(df,instrument)
        state=env.reset()
        total_reward=0
        steps=0

        while True:
            action=agent.act(state)
            next_state,reward,done=env.step(action)
            agent.remember(state,action,reward,next_state,done)
            state=next_state
            total_reward+=reward
            steps+=1

            if steps%10==0:
                agent.replay()

            if done:break

        trades=env.trades
        wins=sum(1 for t in trades if t['pnl']>0)
        total=len(trades)
        wr=wins/total*100 if total>0 else 0
        capital=env.current_capital

        if capital>best_capital:
            best_capital=capital

        episode_results.append({
            'episode':ep+1,
            'capital':capital,
            'trades':total,
            'win_rate':wr,
            'reward':total_reward
        })

        if (ep+1)%10==0:
            print(f'[RL] Ep {ep+1}/{episodes}: Capital=Rs.{capital:,.0f} WR={wr:.1f}% Trades={total} Eps={agent.epsilon:.3f}')

    agent.save(instrument)
    best_ep=max(episode_results,key=lambda x:x['capital'])
    print(f'[RL] Best episode: Capital=Rs.{best_ep["capital"]:,.0f} WR={best_ep["win_rate"]:.1f}%')
    return agent

def get_rl_action(instrument,state):
    agent=DQNAgent()
    if agent.load(instrument):
        agent.epsilon=0  # No exploration in live trading
        return agent.act(state)
    return 0  # HOLD if no model

def candles_to_df(candles):
    import pandas as pd
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:
        df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna().reset_index(drop=True)
