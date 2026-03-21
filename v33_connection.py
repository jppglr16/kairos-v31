"""
V33 Connection Monitor
Proactive internet + API health check
"""
import socket,logging,time
log=logging.getLogger(__name__)

class ConnectionMonitor:
    def __init__(self):
        self.last_ok=True
        self.fail_count=0
        self.alert_sent=False

    def check(self,host="8.8.8.8",port=53,timeout=2):
        """Check internet connectivity"""
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host,port))
            s.close()
            self.fail_count=0
            if not self.last_ok:
                log.info('[NET] Connection restored ✅')
                self.recovered_at=time.time()  # Record recovery time
                self._send_alert('✅ Internet restored! Waiting 60s before trading...')
                self.alert_sent=False
            self.last_ok=True
            return True
        except:
            self.fail_count+=1
            self.last_ok=False
            if self.fail_count>=3 and not self.alert_sent:
                log.warning(f'[NET] Connection unstable! fails={self.fail_count}')
                self._send_alert(f'⚠️ Internet unstable! Trading paused\nFails: {self.fail_count}')
                self.alert_sent=True
            return False

    def check_angel(self):
        """Check Angel One API health"""
        try:
            from v31_angel_trader import angel_trader
            if not angel_trader.connected:
                return False
            return angel_trader.is_connected()
        except:
            return False

    def full_check(self):
        """Full connectivity check with recovery cooldown"""
        internet=self.check()
        if not internet:
            return False,'No internet'

        # Recovery cooldown - wait 60s after reconnect
        if hasattr(self,'recovered_at'):
            elapsed=time.time()-self.recovered_at
            if elapsed<60:
                remaining=int(60-elapsed)
                log.info(f'[NET] Recovery cooldown: {remaining}s remaining')
                return False,f'Recovery cooldown ({remaining}s)'
        angel=self.check_angel()
        if not angel:
            log.warning('[NET] Angel One disconnected! Reconnecting...')
            try:
                from v31_angel_trader import angel_trader
                angel_trader.reconnect()
                time.sleep(3)
                return angel_trader.connected,'Angel reconnected'
            except:
                return False,'Angel reconnect failed'
        return True,'OK'

    def _send_alert(self,msg):
        try:
            from v31_notify import send
            send(msg)
        except:pass

# Global instance
conn_monitor=ConnectionMonitor()
