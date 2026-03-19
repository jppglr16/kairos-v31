import numpy as np
import logging,pickle,os
from collections import deque
log=logging.getLogger(__name__)

class RiskAwareTradingEnv:
    """
    Constrained RL Environment:
    - Sharpe/Sortino ratio rewards
    - CVaR risk constraint
    - Transaction cost penalty
    - Slippage penalty
    """
    def __init__(self,symbol,capital=50000):
        self.symbol=symbol
        self.capital=capital
        self.returns=deque(maxlen=100)
        self.drawdown_history=deque(maxlen=50)
        self.peak_capital=capital
        self.current_capital=capital

        # Risk parameters
        self.transaction_cost=34/capital  # Rs.34 per trade
        self.slippage=0.001               # 0.1% slippage
        self.cvar_limit=0.05              # Max 5% CVaR
        self.max_drawdown=0.20            # Max 20% drawdown

    def get_state(self,features,signal):
        """Build RL state with risk context"""
        try:
            # Risk state features
            drawdown=(self.peak_capital-self.current_capital)/self.peak_capital
            recent_returns=list(self.returns)[-10:] if len(self.returns)>=10 else [0]*10
            volatility=np.std(recent_returns) if recent_returns else 0.01
            mean_return=np.mean(recent_returns) if recent_returns else 0

            risk_features=[
                drawdown,           # Current drawdown
                volatility,         # Return volatility
                mean_return,        # Recent avg return
                self.current_capital/self.capital,  # Capital ratio
                len([r for r in recent_returns if r<0])/max(len(recent_returns),1),  # Loss rate
            ]

            # Combine signal features + risk features
            base_features=features[:30] if len(features)>=30 else features+[0]*(30-len(features))
            state=base_features+risk_features
            return np.array(state,dtype=np.float32)
        except Exception as e:
            log.error(f'[CRL] State error: {e}')
            return np.zeros(35,dtype=np.float32)

    def calculate_sharpe(self,period=20):
        """Calculate Sharpe ratio from recent trades"""
        try:
            rets=list(self.returns)[-period:]
            if len(rets)<5:return 0
            mean=np.mean(rets)
            std=np.std(rets)
            if std==0:return mean*10
            return (mean/std)*np.sqrt(252)  # Annualized
        except:return 0

    def calculate_sortino(self,period=20):
        """Sortino ratio - only penalizes downside"""
        try:
            rets=list(self.returns)[-period:]
            if len(rets)<5:return 0
            mean=np.mean(rets)
            neg_rets=[r for r in rets if r<0]
            if not neg_rets:return mean*10
            downside_std=np.std(neg_rets)
            if downside_std==0:return mean*10
            return (mean/downside_std)*np.sqrt(252)
        except:return 0

    def calculate_cvar(self,confidence=0.95):
        """CVaR - Expected loss in worst 5% cases"""
        try:
            rets=list(self.returns)
            if len(rets)<20:return 0
            sorted_rets=sorted(rets)
            cutoff=int(len(sorted_rets)*(1-confidence))
            worst=sorted_rets[:max(1,cutoff)]
            return abs(np.mean(worst))
        except:return 0

    def calculate_reward(self,pnl,signal,trade_taken):
        """
        Risk-adjusted reward:
        1. Base: Sortino ratio contribution
        2. Penalty: Transaction costs
        3. Penalty: Slippage
        4. Penalty: CVaR violation
        5. Penalty: Drawdown
        """
        try:
            ret=pnl/self.capital

            # Update history
            self.returns.append(ret)
            self.current_capital+=pnl
            if self.current_capital>self.peak_capital:
                self.peak_capital=self.current_capital

            # 1. Base reward = Sortino contribution
            sortino=self.calculate_sortino()
            sharpe=self.calculate_sharpe()
            base_reward=(sortino+sharpe)/2 * (1 if pnl>0 else -1)

            # 2. Transaction cost penalty
            tc_penalty=self.transaction_cost*2  # Buy + sell
            base_reward-=tc_penalty

            # 3. Slippage penalty
            sl_penalty=self.slippage*abs(ret)
            base_reward-=sl_penalty

            # 4. CVaR constraint penalty
            cvar=self.calculate_cvar()
            if cvar>self.cvar_limit:
                cvar_penalty=(cvar-self.cvar_limit)*10
                base_reward-=cvar_penalty
                log.warning(f'[CRL] CVaR exceeded: {cvar:.3f} > {self.cvar_limit}')

            # 5. Drawdown penalty
            drawdown=(self.peak_capital-self.current_capital)/self.peak_capital
            if drawdown>0.10:
                dd_penalty=drawdown*5
                base_reward-=dd_penalty

            # 6. Regime bonus/penalty
            regime=signal.get('regime','')
            if regime in ['TRENDING_UP','TRENDING_UP_HV'] and pnl>0:
                base_reward*=1.3  # Reward trending wins
            elif regime=='RANGING' and pnl<0:
                base_reward*=1.5  # Extra penalty for ranging losses

            # 7. Score quality bonus
            score=signal.get('score',0)
            if score>=22 and pnl>0:
                base_reward*=1.2  # Reward high-quality wins

            log.info(f'[CRL] Reward: base={base_reward:.3f} sortino={sortino:.2f} cvar={cvar:.3f}')
            return round(base_reward,4)

        except Exception as e:
            log.error(f'[CRL] Reward error: {e}')
            return 1.0 if pnl>0 else -1.0

    def should_skip_for_risk(self,signal):
        """
        Pre-trade risk check:
        Skip if risk constraints violated
        """
        try:
            # Check drawdown limit
            drawdown=(self.peak_capital-self.current_capital)/self.peak_capital
            if drawdown>self.max_drawdown:
                return True,'MAX_DRAWDOWN_EXCEEDED'

            # Check CVaR
            cvar=self.calculate_cvar()
            if cvar>self.cvar_limit*1.5:
                return True,'CVAR_LIMIT_EXCEEDED'

            # Check recent loss streak
            recent=list(self.returns)[-5:]
            if len(recent)>=5 and all(r<0 for r in recent):
                return True,'5_CONSECUTIVE_LOSSES'

            return False,'RISK_OK'
        except:
            return False,'ERROR'


class ConstrainedQLearning:
    """
    Q-Learning with risk constraints
    Uses neural network for Q-value approximation
    """
    def __init__(self,symbol,state_size=35,action_size=3):
        self.symbol=symbol
        self.state_size=state_size
        self.action_size=action_size  # 0=Skip, 1=BUY, 2=SELL
        self.memory=deque(maxlen=2000)
        self.epsilon=1.0
        self.epsilon_min=0.01
        self.epsilon_decay=0.995
        self.learning_rate=0.001
        self.gamma=0.95
        self.model=None
        self._build_model()

    def _build_model(self):
        """Neural network for Q-values"""
        try:
            from sklearn.neural_network import MLPRegressor
            self.model=MLPRegressor(
                hidden_layer_sizes=(64,64,32),
                max_iter=1,
                warm_start=True,
                learning_rate_init=self.learning_rate
            )
            # Initialize with dummy data
            X=np.random.rand(10,self.state_size)
            y=np.random.rand(10,self.action_size)
            # MLPRegressor needs 1D y
            self.models=[MLPRegressor(
                hidden_layer_sizes=(64,32),
                max_iter=1,warm_start=True
            ) for _ in range(self.action_size)]
            for i,m in enumerate(self.models):
                m.fit(X,y[:,i])
        except Exception as e:
            log.error(f'[CRL] Model build error: {e}')

    def get_q_values(self,state):
        """Get Q-values for all actions"""
        try:
            X=state.reshape(1,-1)
            return np.array([m.predict(X)[0] for m in self.models])
        except:
            return np.zeros(self.action_size)

    def select_action(self,state,risk_env,signal):
        """Select action with risk constraints"""
        try:
            # Check risk constraints first
            skip,reason=risk_env.should_skip_for_risk(signal)
            if skip:
                log.info(f'[CRL] Risk skip: {reason}')
                return 0  # Skip action

            # Epsilon-greedy
            if np.random.random()<self.epsilon:
                return np.random.randint(self.action_size)

            q_values=self.get_q_values(state)
            return int(np.argmax(q_values))
        except:
            return 1  # Default BUY

    def update(self,state,action,reward,next_state):
        """Update Q-values"""
        try:
            self.memory.append((state,action,reward,next_state))
            if len(self.memory)<32:return

            # Sample batch
            indices=np.random.choice(len(self.memory),32,replace=False)
            batch=[self.memory[i] for i in indices]

            for s,a,r,ns in batch:
                target=r+self.gamma*np.max(self.get_q_values(ns))
                X=s.reshape(1,-1)
                self.models[a].partial_fit(X,[target])

            # Decay epsilon
            if self.epsilon>self.epsilon_min:
                self.epsilon*=self.epsilon_decay
        except Exception as e:
            log.error(f'[CRL] Update error: {e}')

    def save(self):
        fname=f'ml_models/{self.symbol}_v31_crl.pkl'
        pickle.dump(self,open(fname,'wb'))

    def load(self,symbol):
        fname=f'ml_models/{symbol}_v31_crl.pkl'
        if os.path.exists(fname):
            return pickle.load(open(fname,'rb'))
        return self


# Global instances
_crl_agents={}
_risk_envs={}

def get_crl_agent(symbol,capital=50000):
    if symbol not in _crl_agents:
        _crl_agents[symbol]=ConstrainedQLearning(symbol)
        _crl_agents[symbol].load(symbol)
    return _crl_agents[symbol]

def get_risk_env(symbol,capital=50000):
    if symbol not in _risk_envs:
        _risk_envs[symbol]=RiskAwareTradingEnv(symbol,capital)
    return _risk_envs[symbol]

def crl_should_trade(symbol,signal,features,capital=50000):
    """
    Main function: Should we take this trade?
    Returns (should_trade, action, reason)
    """
    try:
        agent=get_crl_agent(symbol,capital)
        env=get_risk_env(symbol,capital)
        state=env.get_state(features,signal)

        # Check risk first
        skip,reason=env.should_skip_for_risk(signal)
        if skip:return False,0,reason

        # Check if agent has enough experience
        if len(agent.memory)<50:
            # Not enough training - allow trade
            return True,1,'CRL_NEW_AGENT'

        action=agent.select_action(state,env,signal)
        # 0=Skip, 1=BUY, 2=SELL
        if action==0:return False,0,'CRL_SKIP'

        sig_action=signal.get('action','BUY')
        if action==1 and sig_action!='BUY':return False,0,'CRL_DIRECTION_MISMATCH'
        if action==2 and sig_action!='SELL':return False,0,'CRL_DIRECTION_MISMATCH'

        return True,action,'CRL_OK'
    except Exception as e:
        log.error(f'[CRL] Error: {e}')
        return True,1,'CRL_ERROR'

def crl_update_outcome(symbol,signal,features,pnl,capital=50000):
    """Update CRL after trade outcome"""
    try:
        agent=get_crl_agent(symbol,capital)
        env=get_risk_env(symbol,capital)
        state=env.get_state(features,signal)
        reward=env.calculate_reward(pnl,signal,True)
        next_state=env.get_state(features,signal)
        action=1 if pnl>0 else 2
        agent.update(state,action,reward,next_state)
        agent.save()
        log.info(f'[CRL] {symbol} updated: reward={reward:.3f} pnl={pnl}')
    except Exception as e:
        log.error(f'[CRL] Update error: {e}')
