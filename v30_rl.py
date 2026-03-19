import json,os,numpy as np
from datetime import datetime

class RLAgent:
    def __init__(self,instrument):
        self.instrument=instrument
        self.file=f'rl_{instrument}.json'
        self.state=self.load()

    def load(self):
        if os.path.exists(self.file):
            return json.load(open(self.file))
        return {
            'q_table':{},
            'episodes':0,
            'total_reward':0,
            'epsilon':1.0,
            'learning_rate':0.1,
            'discount':0.95,
            'best_reward':-999,
            'action_counts':{'BUY':0,'SELL':0,'SKIP':0}
        }

    def save(self):
        json.dump(self.state,open(self.file,'w'),indent=2)

    def get_state_key(self,features):
        try:
            rsi_bucket=int(features.get('rsi',50)//10)*10
            trend='UP' if features.get('trend15',0)>0 else 'DOWN'
            vol='HIGH' if features.get('vol_ratio',1)>1.5 else 'NORMAL'
            hour=features.get('hour',10)
            hour_bucket='MORNING' if hour<11 else 'MIDDAY' if hour<13 else 'AFTERNOON'
            macd='POS' if features.get('macd_hist',0)>0 else 'NEG'
            return f'{rsi_bucket}_{trend}_{vol}_{hour_bucket}_{macd}'
        except:
            return 'DEFAULT'

    def get_q_value(self,state,action):
        return self.state['q_table'].get(f'{state}_{action}',0.0)

    def update_q(self,state,action,reward,next_state):
        key=f'{state}_{action}'
        old_q=self.get_q_value(state,action)
        next_max=max([self.get_q_value(next_state,a) for a in ['BUY','SELL','SKIP']])
        lr=self.state['learning_rate']
        gamma=self.state['discount']
        new_q=old_q+lr*(reward+gamma*next_max-old_q)
        self.state['q_table'][key]=round(new_q,4)
        self.state['total_reward']+=reward
        self.state['episodes']+=1
        # Decay epsilon
        if self.state['epsilon']>0.1:
            self.state['epsilon']*=0.995
        self.save()

    def choose_action(self,features,smc_action):
        state=self.get_state_key(features)
        epsilon=self.state['epsilon']
        # Explore
        if np.random.random()<epsilon:
            return smc_action if smc_action else 'SKIP'
        # Exploit
        q_buy=self.get_q_value(state,'BUY')
        q_sell=self.get_q_value(state,'SELL')
        q_skip=self.get_q_value(state,'SKIP')
        best=max(q_buy,q_sell,q_skip)
        if best==q_skip:return 'SKIP'
        if best==q_buy:return 'BUY'
        return 'SELL'

    def learn_from_trade(self,entry_features,action,pnl,exit_features):
        reward=self.calculate_reward(pnl)
        state=self.get_state_key(entry_features)
        next_state=self.get_state_key(exit_features) if exit_features else state
        self.update_q(state,action,reward,next_state)
        self.state['action_counts'][action]=self.state['action_counts'].get(action,0)+1
        print(f'[RL] {self.instrument} Learned: {action} reward:{reward:.2f} epsilon:{self.state["epsilon"]:.3f}')

    def calculate_reward(self,pnl):
        if pnl>5000:return 10
        elif pnl>2500:return 5
        elif pnl>0:return 2
        elif pnl>-1000:return -1
        elif pnl>-2500:return -3
        else:return -5

    def get_confidence_boost(self,features,action):
        state=self.get_state_key(features)
        q=self.get_q_value(state,action)
        skip_q=self.get_q_value(state,'SKIP')
        if q>skip_q:return min(20,int(q*10))
        return -10

    def print_stats(self):
        print(f'[RL] {self.instrument}: Episodes:{self.state["episodes"]} Reward:{self.state["total_reward"]:.1f} Epsilon:{self.state["epsilon"]:.3f}')
        print(f'[RL] Actions: {self.state["action_counts"]}')

rl_agents={}

def get_rl_agent(instrument):
    if instrument not in rl_agents:
        rl_agents[instrument]=RLAgent(instrument)
    return rl_agents[instrument]

def rl_should_trade(instrument,features,smc_action):
    agent=get_rl_agent(instrument)
    action=agent.choose_action(features,smc_action)
    boost=agent.get_confidence_boost(features,smc_action) if smc_action else 0
    return action,boost

def rl_record_result(instrument,entry_features,action,pnl,exit_features=None):
    agent=get_rl_agent(instrument)
    agent.learn_from_trade(entry_features,action,pnl,exit_features)
