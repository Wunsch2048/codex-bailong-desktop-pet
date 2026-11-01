"""Stable semantic selection from existing snapshots, never a FIFO of messages."""
from status_reactions import ACTIVE,classify,Reaction

class ContinuousWork:
    def __init__(self,stable_seconds=1.5,switch_seconds=3.,minimum_hold=6.):
        self.stable_seconds=stable_seconds;self.owner=None;self.candidate=None;self.since=0.;self.next_check=0.;self.current=None
        self.switch_seconds=max(stable_seconds,switch_seconds);self.minimum_hold=minimum_hold
        self.observed_at=0.;self.owner_since=0.
    def clear(self):
        self.owner=None;self.candidate=None;self.current=None;self.next_check=0.
        self.owner_since=0.
    def commit(self,reaction,now=None):
        # target() and commit() share the caller's business clock. Residency
        # starts when the animation actually starts, not on an incoming label.
        self.owner=reaction;self.owner_since=self.observed_at if now is None else now
    def target(self,reactions,now,enabled=True):
        self.observed_at=now
        if not enabled or reactions.present is False or reactions.completion:
            self.current=None;self.candidate=None;self.next_check=0.;return None
        def eligible(e):
            return e and e['state'] in ACTIVE and reactions.fresh(e,now)
        cached=reactions.sessions.get(self.current.session) if self.current else None
        can_reuse=not self.current or (eligible(cached) and cached.get('turn')==self.current.turn)
        # Throttle ordinary labels, never reuse an active result after a
        # terminal state, expired lease, or a new turn invalidated its identity.
        if now<self.next_check and can_reuse:return self.current
        self.next_check=now+.15
        held=reactions.sessions.get(self.owner.session) if self.owner else None
        if not eligible(held) or self.owner and held.get('turn')!=self.owner.turn:held=None
        event=held or next((e for e in reversed(reactions.sessions.values()) if eligible(e)),None)
        if event is None:self.candidate=None;self.current=None;return None
        # A lease proves ongoing work, not that a 90-second-old command is
        # still executing. Use a generic work pose without inventing new text.
        semantic=dict(event,state='thinking',activity='',text='',display='') if event['state']!='thinking' and now-event['received']>90 else event
        selected=classify(semantic,reactions.action_ids)
        result=Reaction(selected.kind,selected.action_id,str(event['session']),str(event['turn'])) if selected else None
        key=(result.session,result.turn,result.action_id) if result else None
        if key!=self.candidate:self.candidate=key;self.since=now
        same_turn=bool(self.owner and held)
        owner_key=(self.owner.session,self.owner.turn,self.owner.action_id) if self.owner else None
        if same_turn and key==owner_key:
            # A speculative switch may not have reached a safe boundary yet.
            # Returning to the playing action cancels it immediately; keeping
            # the speculative current value here used to close/reopen props.
            self.current=result
        elif now-self.since>=(self.switch_seconds if same_turn else self.stable_seconds) and (not same_turn or now-self.owner_since>=self.minimum_hold):
            self.current=result
        elif same_turn:
            self.current=self.owner
        else:self.current=None
        return self.current
