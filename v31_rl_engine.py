import numpy as np
import json,os,pickle
from datetime import datetime
import logging
log=logging.getLogger(__name__)

# ============================================================
# REINFORCEMENT LEARNING ENGINE
# Agent learns optimal trading policy from 3 years data
# ============================================================

class TradingEnvironment:
    """
    Market environment for RL agent:
    State = market features
    Action = BUY/SELL/HOLD
    Reward = PnL
    """
    def __init__(self,df,atr_multiplier=1.0):
        self.df=df
        self.atr_mult=atr_multiplier
        self.reset()

    def reset(self):
        self.idx=60
        self.position=0  # 0=flat, 1=long, -1=short
        self.entry=0
        self.pnl=0
        return self._get_state()

    def _get_state(self):
        try:
            df5=self.df.iloc[self.idx-60:self.idx]
            c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
            atr=float((h-l).tail(14).mean())
            cur=float(c.iloc[-1])

            # Price features
            ret1=(cur-float(c.iloc[-2]))/float(c.iloc[-2])
            ret5=(cur-float(c.iloc[-6]))/float(c.iloc[-6]) if len(c)>6 else 0
            ret10=(cur-float(c.iloc[-11]))/float(c.iloc[-11]) if len(c)>11 else 0

            # Indicators
            d=c.diff();g=d.clip(lower=0).rolling(14).mean()
            ll=-d.clip(upper=0).rolling(14).mean()
            rsi=float((100-(100/(1+g/ll))).iloc[-1])

            # Moving averages
            ma20=float(c.rolling(20).mean().iloc[-1])
            ma50=float(c.rolling(50).mean().iloc[-1]) if len(c)>=50 else ma20

            # Volume
            vol_avg=float(v.rolling(20).mean().iloc[-1])
            vol_ratio=float(v.iloc[-1])/vol_avg if vol_avg>0 else 1

            # ATR
            atr_pct=atr/cur if cur>0 else 0

            # Position
            pos_profit=0
            if self.position!=0 and self.entry>0:
                pos_profit=(cur-self.entry)/self.entry if self.position==1 else (self.entry-cur)/self.entry

            state=np.array([
                ret1,ret5,ret10,
                rsi/100,(rsi-50)/50,
                (cur-ma20)/ma20 if ma20>0 else 0,
                (ma20-ma50)/ma50 if ma50>0 else 0,
                min(vol_ratio,3)/3,
                atr_pct*100,
                pos_profit,
                float(self.position),
            ],dtype=np.float32)
            return state
        except:
            return np.zeros(11,dtype=np.float32)

    def step(self,action):
        """
        Actions: 0=HOLD, 1=BUY, 2=SELL
        Returns: state, reward, done
        """
        reward=0
        done=False

        df5=self.df.iloc[self.idx-60:self.idx]
        cur=float(df5['close'].iloc[-1])
        atr=float((df5['high']-df5['low']).tail(14).mean())
        sl=atr*self.atr_mult

        # Execute action
        if action==1 and self.position==0:  # BUY
            self.position=1
            self.entry=cur
            reward=-0.001  # Small cost to open

        elif action==2 and self.position==0:  # SELL
            self.position=-1
            self.entry=cur
            reward=-0.001

        elif action==0 and self.position!=0:  # CLOSE
            if self.position==1:
                pnl=(cur-self.entry)/self.entry
            else:
                pnl=(self.entry-cur)/self.entry
            reward=pnl*10  # Scale reward
            self.pnl+=pnl
            self.position=0
            self.entry=0

        # Auto-close on SL or target
        if self.position==1:
            if cur<=self.entry-sl:
                reward=-1.0;self.position=0;self.entry=0
            elif cur>=self.entry+sl*2:
                reward=2.0;self.position=0;self.entry=0
        elif self.position==-1:
            if cur>=self.entry+sl:
                reward=-1.0;self.position=0;self.entry=0
            elif cur<=self.entry-sl*2:
                reward=2.0;self.position=0;self.entry=0

        self.idx+=1
        if self.idx>=len(self.df)-10:
            done=True
            if self.position!=0:
                reward+=-0.5  # Penalty for open position at end

        state=self._get_state()
        return state,reward,done

class QLearningAgent:
    """
    Q-Learning agent with neural network
    Learns optimal trading policy
    """
    def __init__(self,state_size=11,action_size=3):
        self.state_size=state_size
        self.action_size=action_size
        self.memory=[]
        self.gamma=0.95      # Discount factor
        self.epsilon=1.0     # Exploration rate
        self.epsilon_min=0.01
        self.epsilon_decay=0.995
        self.learning_rate=0.001
        self.model=self._build_model()

    def _build_model(self):
        try:
            from sklearn.neural_network import MLPRegressor
            model=MLPRegressor(
                hidden_layer_sizes=(64,64,32),
                activation='relu',
                learning_rate_init=self.learning_rate,
                max_iter=1,
                warm_start=True,
                random_state=42
            )
            # Initialize with dummy data
            dummy_x=np.zeros((10,self.state_size))
            dummy_y=np.zeros((10,self.action_size))
            model.fit(dummy_x,dummy_y)
            return model
        except:return None

    def remember(self,state,action,reward,next_state,done):
        self.memory.append((state,action,reward,next_state,done))
        if len(self.memory)>2000:
            self.memory.pop(0)

    def act(self,state):
        if np.random.random()<=self.epsilon:
            return np.random.randint(self.action_size)
        try:
            q_values=self.model.predict([state])[0]
            return np.argmax(q_values)
        except:return 0

    def replay(self,batch_size=32):
        if len(self.memory)<batch_size:return
        try:
            import random
            batch=random.sample(self.memory,batch_size)
            states=np.array([e[0] for e in batch])
            targets=[]
            for state,action,reward,next_state,done in batch:
                target=reward
                if not done:
                    next_q=self.model.predict([next_state])[0]
                    target=reward+self.gamma*np.max(next_q)
                current_q=self.model.predict([state])[0].copy()
                current_q[action]=target
                targets.append(current_q)
            self.model.fit(states,np.array(targets))
            if self.epsilon>self.epsilon_min:
                self.epsilon*=self.epsilon_decay
        except:pass

    def get_action_probs(self,state):
        """Get probability of each action"""
        try:
            q=self.model.predict([state])[0]
            # Softmax
            e_q=np.exp(q-np.max(q))
            return e_q/e_q.sum()
        except:return np.array([0.33,0.33,0.34])

def train_rl_agent(symbol,df,episodes=50):
    """Train RL agent on historical data"""
    print(f'[RL] Training {symbol} for {episodes} episodes...')

    env=TradingEnvironment(df)
    agent=QLearningAgent()

    best_reward=-999
    best_agent=None

    for ep in range(episodes):
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

            if done:break

        agent.replay(32)

        if total_reward>best_reward:
            best_reward=total_reward
            best_agent=pickle.loads(pickle.dumps(agent))

        if ep%10==0:
            print(f'[RL] {symbol} ep:{ep}/{episodes} '
                  f'reward:{total_reward:.2f} '
                  f'epsilon:{agent.epsilon:.3f}')

    # Save best agent
    os.makedirs('ml_models',exist_ok=True)
    pickle.dump(best_agent,
                open(f'ml_models/{symbol}_v31_rl.pkl','wb'))
    print(f'[RL] ✅ {symbol}: Best reward={best_reward:.2f} saved!')
    return best_agent

def get_rl_signal(symbol,df5,current_price):
    """
    Get RL agent's recommendation:
    Returns: action(0=hold,1=buy,2=sell), confidence
    """
    try:
        rl_file=f'ml_models/{symbol}_v31_rl.pkl'
        if not os.path.exists(rl_file):return 0,0.33

        agent=pickle.load(open(rl_file,'rb'))
        env=TradingEnvironment(df5)
        state=env._get_state()
        probs=agent.get_action_probs(state)

        action=np.argmax(probs)
        confidence=float(probs[action])
        return int(action),confidence

    except Exception as e:
        log.error(f'[RL] Error {symbol}: {e}')
        return 0,0.33
