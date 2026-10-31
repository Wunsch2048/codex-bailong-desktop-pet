"""Temporary attached-panel state during a character drag; no saved-mode writes."""
import time

class DragPanel:
    def __init__(self,pet):self.pet=pet;self.active=False
    def settle(self):
        t=self.pet.bubble.size_transition
        t.complete();t.release_landing()
    def begin(self):
        p=self.pet;b=p.bubble
        if self.active or p.settings.get('panel_detached') or not b.enabled or not b.isVisible():return
        self.settle();self.was_compact=b.is_compact();self.active=True;self.position=p.pos()
        if b.report and b.report.requested:b.report.dismiss()
        before=b.compact_kind();kind='minimal' if b.bubble_mode=='minimal' else 'mini'
        edge=getattr(p,'edge_dock',None);leaving_edge=bool(edge and (edge.active or edge.amount>0))
        # Fold exit and drag collection are one transaction, not two owners
        # committing successive compact surfaces at the old dock position.
        changed=before!=kind
        t=b.size_transition
        if changed or leaving_edge:t.begin()
        b._drag_compact_kind=kind
        if leaving_edge:
            edge.clear(immediate=True,update_panel=False)
            b._edge_compact=False;b._pending_edge_compact=None
        b.expanded=False;b.panel_page='status';b._editor_origin=None;b._editor_positioned=False;b._editing_flags(False)
        if changed:b.redraw()
        if changed or leaving_edge:t.commit(preserve_reveals=not changed)
    def follow(self):
        if not self.active:return
        p=self.pet;t=p.bubble.size_transition;delta=p.pos()-self.position;self.position=p.pos()
        if t.running:t.translate(delta)
        elif t.landing.image is not None:t.release_landing()
    def finish(self,docked=False):
        if not self.active:return
        p=self.pet;b=p.bubble
        self.settle();self.active=False
        t=b.size_transition;before=b.compact_kind()
        if docked:b.auto_compact=True;b._minimal_normal_open=False
        elif not self.was_compact:
            b.auto_compact=False;b._minimal_normal_open=b.bubble_mode in ('minimal','mini')
            b.expanded=False;b.panel_page='status';b._manual_grace_until=time.monotonic()+15
        elif b.bubble_mode=='auto':b.auto_compact=True;b._minimal_normal_open=False
        b._drag_compact_kind=None
        if before!=b.compact_kind():
            b._drag_compact_kind=before;t.begin();b._drag_compact_kind=None
            b.redraw();t.commit()
        else:p.position_bubble()
