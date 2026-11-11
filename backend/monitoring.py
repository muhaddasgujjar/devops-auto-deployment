"""Versioned alert evaluation and transactional at-least-once local delivery."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.service import Conflict

POLICY = {'id':'local-monitoring-v1','maximum_attempts':5,'lease_seconds':45,
          'retry_seconds':[5,15,30,60,120],'probe_maximum_age_seconds':30,
          'native_rules':['DemoPodsUnavailable','DemoRequestErrors','DemoRequestLatency']}


def canonical(payload):
    return json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class MonitoringService:
    def __init__(self,service):
        self.service,self.db,self.t,self.env_id=service,service.db,service.t,service.env_id

    def lock(self,conn):
        return conn.execute(select(self.t('environments')).where(
            self.t('environments').c.id==self.env_id).with_for_update()).mappings().one()

    def evaluate(self,conn,actor):
        env=self.lock(conn); now=datetime.now(timezone.utc)
        desired=self.service.release(conn,env['desired_release_id'])
        stable=self.service.release(conn,env['stable_release_id'])
        def identity(item):
            return {k:item[k] for k in ('id','environment_commit','status')} | {
                'build':item['build']['number'],'source':item['build']['source_commit'],
                'image':item['artifact']['image']} if item else None
        context={'policy':POLICY['id'],'environment':self.env_id,
                 'desired':identity(desired),'stable':identity(stable)}
        conditions={}
        def add(kind,subject,detail): conditions[kind+':'+subject]=(kind,subject,detail)
        if desired and desired['status'] in ('rejected','readiness_aborted','aborted'):
            add('candidate_rejected',desired['id'],{'decision':desired['status']})
        if desired and desired['status'] in ('inconclusive','telemetry_error'):
            add('candidate_inconclusive',desired['id'],{'decision':desired['status']})
        recent=conn.execute(select(self.t('recoveries')).where(self.t('recoveries').c.environment_id==self.env_id)
            .order_by(self.t('recoveries').c.created_at.desc()).limit(1)).mappings().first()
        if recent and desired and (desired['id']==recent['origin_release_id'] or desired['recovery_id']==recent['id']):
            if recent['phase'] in ('proposed','applying','verifying'):
                add('post_promotion_incident',recent['id'],{'phase':recent['phase']})
            elif recent['phase']=='failed':
                add('recovery_failed',recent['id'],{'outcome':recent['outcome']})
        if env['source_uid'] and (env['freshness']!='current' or not env['last_observed_at'] or
            not 0 <= (now-env['last_observed_at']).total_seconds() <= self.service.settings.stale_seconds):
            add('observation_unavailable',self.env_id,{'source':'controller','freshness':env['freshness']})
        monitor=conn.execute(select(self.t('monitoring_state')).where(
            self.t('monitoring_state').c.environment_id==self.env_id)).mappings().first()
        if monitor and monitor['checked_at']:
            if not 0 <= (now-monitor['checked_at']).total_seconds() <= 60:
                add('monitor_unavailable',self.env_id,{'source':'notification_worker'})
            elif not monitor['telemetry_available']:
                add('telemetry_unavailable',self.env_id,{'source':'prometheus'})
            else:
                for item in monitor['native_alerts']:
                    if item['state']=='firing':
                        add('workload_signal',item['name']+':'+item['revision'],item)
        table=self.t('monitoring_alerts')
        rows={r['condition_key']:r for r in conn.execute(select(table).where(table.c.environment_id==self.env_id)).mappings()}
        # Loss of telemetry cannot resolve an already firing workload signal.
        # Keep it open until a fresh successful Prometheus probe supplies evidence.
        scrapes_uncertain=bool(monitor and any(x['name']=='DemoPodsUnavailable' for x in monitor['native_alerts']))
        if not monitor or not monitor['checked_at'] or not monitor['telemetry_available'] or scrapes_uncertain or not 0 <= (now-monitor['checked_at']).total_seconds() <= 60:
            for key,row in rows.items():
                if row['kind']=='workload_signal' and row['state']=='firing':
                    conditions.setdefault(key,(row['kind'],row['subject'],row['data']['detail']))
        for key in sorted(set(conditions)|{k for k,r in rows.items() if r['state']=='firing'}):
            row=rows.get(key); state='firing' if key in conditions else 'resolved'
            if row and row['state']==state: continue
            kind,subject,detail=conditions[key] if key in conditions else (row['kind'],row['subject'],{})
            alert_id=row['id'] if row else str(uuid.uuid4())
            generation=(row['generation']+(state=='firing')) if row else 1
            data={**context,'detail':detail}
            if row:
                conn.execute(table.update().where(table.c.id==alert_id).values(
                    state=state,generation=generation,data=data,updated_at=now))
            else:
                conn.execute(table.insert().values(id=alert_id,environment_id=self.env_id,condition_key=key,
                    kind=kind,subject=subject,state=state,generation=generation,data=data))
            event_id=str(uuid.uuid4()); notification_id=str(uuid.uuid4())
            conn.execute(self.t('monitoring_events').insert().values(id=event_id,alert_id=alert_id,
                generation=generation,state=state,actor=actor,data=data))
            payload={'id':notification_id,'event_id':event_id,'alert_id':alert_id,'kind':kind,'state':state,
                     'subject':subject,'generation':generation,**data}
            conn.execute(self.t('notification_outbox').insert().values(id=notification_id,environment_id=self.env_id,
                event_id=event_id,payload=payload,payload_sha256=hashlib.sha256(canonical(payload)).hexdigest()))

    def tick(self,envelope,actor):
        now=datetime.now(timezone.utc)
        if envelope.observed_at.tzinfo is None or not 0 <= (now-envelope.observed_at).total_seconds() <= 30:
            raise ValueError('Monitoring probe must be recent UTC evidence')
        with self.db.engine.begin() as conn:
            self.lock(conn)
            table=self.t('monitoring_state')
            previous=conn.execute(select(table).where(table.c.environment_id==self.env_id)).mappings().first()
            if previous and previous['checked_at'] and envelope.observed_at < previous['checked_at']:
                raise Conflict('Older monitoring probe cannot overwrite current state')
            values=dict(checked_at=envelope.observed_at,telemetry_available=envelope.telemetry_available,
                        native_alerts=[x.model_dump() for x in envelope.alerts])
            conn.execute(insert(table).values(environment_id=self.env_id,**values).on_conflict_do_update(
                index_elements=['environment_id'],set_=values))
            self.evaluate(conn,actor)
        return {'accepted':True,'policy':POLICY['id']}

    def snapshot(self):
        with self.db.engine.connect() as conn:
            alerts=[dict(x) for x in conn.execute(select(self.t('monitoring_alerts')).where(
                self.t('monitoring_alerts').c.environment_id==self.env_id).order_by(
                    self.t('monitoring_alerts').c.updated_at.desc()).limit(100)).mappings()]
            state=conn.execute(select(self.t('monitoring_state')).where(
                self.t('monitoring_state').c.environment_id==self.env_id)).mappings().first()
            rows=[dict(x) for x in conn.execute(select(self.t('notification_outbox')).where(
                self.t('notification_outbox').c.environment_id==self.env_id).order_by(
                    self.t('notification_outbox').c.sequence.desc()).limit(100)).mappings()]
            events=[dict(x) for x in conn.execute(select(self.t('notification_events')).join(
                self.t('notification_outbox'),self.t('notification_outbox').c.id==self.t('notification_events').c.notification_id)
                .where(self.t('notification_outbox').c.environment_id==self.env_id)
                .order_by(self.t('notification_events').c.created_at.desc()).limit(200)).mappings()]
        for row in rows: row.pop('lease_id',None)
        fresh=bool(state and state['checked_at'] and 0 <= (datetime.now(timezone.utc)-state['checked_at']).total_seconds() <= 60)
        return {'policy':POLICY,'probe':dict(state) if state else None,'fresh':fresh,
                'alerts':alerts,'notifications':rows,'delivery_events':events}

    def log(self,conn,row,phase,**data):
        conn.execute(self.t('notification_events').insert().values(id=str(uuid.uuid4()),
            notification_id=row['id'],attempt=row['attempts'],phase=phase,data=data))

    def claim(self,actor):
        now=datetime.now(timezone.utc); table=self.t('notification_outbox')
        with self.db.engine.begin() as conn:
            self.lock(conn)
            rows=conn.execute(select(table).where(table.c.environment_id==self.env_id,
                table.c.state.in_(('pending','leased')))
                .order_by(table.c.sequence).with_for_update(skip_locked=True).limit(20)).mappings()
            for item in rows:
                row=dict(item)
                if row['next_attempt_at']>now: return None
                if row['state']=='leased':
                    if row['lease_until']>now: return None
                    self.log(conn,row,'expired',actor=actor)
                if row['attempts']>=5:
                    conn.execute(table.update().where(table.c.id==row['id']).values(state='dead',lease_id=None,lease_until=None))
                    self.log(conn,row,'dead',actor=actor,reason='attempt_limit'); continue
                row.update(state='leased',attempts=row['attempts']+1,lease_id=str(uuid.uuid4()),lease_until=now+timedelta(seconds=45))
                conn.execute(table.update().where(table.c.id==row['id']).values(**{k:row[k] for k in
                    ('state','attempts','lease_id','lease_until')}))
                self.log(conn,row,'claimed',actor=actor)
                return row
        return None

    def finish(self,notification_id,envelope,actor):
        now=datetime.now(timezone.utc); table=self.t('notification_outbox')
        with self.db.engine.begin() as conn:
            self.lock(conn)
            row=conn.execute(select(table).where(table.c.id==notification_id,
                table.c.environment_id==self.env_id).with_for_update()).mappings().first()
            if not row or row['state']!='leased' or row['lease_id']!=envelope.lease_id or row['lease_until']<now:
                raise Conflict('Delivery lease is no longer owned; reconcile current state')
            if envelope.delivered and (envelope.receipt_id!=row['id'] or envelope.receipt_sha256!=row['payload_sha256']):
                raise ValueError('Receiver receipt does not match the immutable notification')
            phase='delivered' if envelope.delivered else ('dead' if row['attempts']>=5 else 'retry')
            conn.execute(table.update().where(table.c.id==row['id']).values(
                state='pending' if phase=='retry' else phase,lease_id=None,lease_until=None,
                delivered_at=now if phase=='delivered' else None,
                next_attempt_at=now+timedelta(seconds=POLICY['retry_seconds'][row['attempts']-1])))
            self.log(conn,row,phase,actor=actor,result=envelope.result,receipt_sha256=envelope.receipt_sha256)
        return {'state':'pending' if phase=='retry' else phase}
