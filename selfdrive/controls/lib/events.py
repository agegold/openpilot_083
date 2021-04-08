from enum import IntEnum
from typing import Dict, Union, Callable, Any

from cereal import log, car
import cereal.messaging as messaging
from common.realtime import DT_CTRL
from selfdrive.config import Conversions as CV
from selfdrive.locationd.calibrationd import MIN_SPEED_FILTER

AlertSize = log.ControlsState.AlertSize
AlertStatus = log.ControlsState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = car.CarEvent.EventName

# Alert priorities
class Priority(IntEnum):
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5

# Event types
class ET:
  ENABLE = 'enable'
  PRE_ENABLE = 'preEnable'
  NO_ENTRY = 'noEntry'
  WARNING = 'warning'
  USER_DISABLE = 'userDisable'
  SOFT_DISABLE = 'softDisable'
  IMMEDIATE_DISABLE = 'immediateDisable'
  PERMANENT = 'permanent'

# get event name from enum
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}


class Events:
  def __init__(self):
    self.events = []
    self.static_events = []
    self.events_prev = dict.fromkeys(EVENTS.keys(), 0)

  @property
  def names(self):
    return self.events

  def __len__(self):
    return len(self.events)

  def add(self, event_name, static=False):
    if static:
      self.static_events.append(event_name)
    self.events.append(event_name)

  def clear(self):
    self.events_prev = {k: (v+1 if k in self.events else 0) for k, v in self.events_prev.items()}
    self.events = self.static_events.copy()

  def any(self, event_type):
    for e in self.events:
      if event_type in EVENTS.get(e, {}).keys():
        return True
    return False

  def create_alerts(self, event_types, callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.events_prev[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME[e]}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      self.events.append(e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = car.CarEvent.new_message()
      event.name = event_name
      for event_type in EVENTS.get(event_name, {}).keys():
        setattr(event, event_type , True)
      ret.append(event)
    return ret

class Alert:
  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status: log.ControlsState.AlertStatus,
               alert_size: log.ControlsState.AlertSize,
               alert_priority: Priority,
               visual_alert: car.CarControl.HUDControl.VisualAlert,
               audible_alert: car.CarControl.HUDControl.AudibleAlert,
               duration_sound: float,
               duration_hud_alert: float,
               duration_text: float,
               alert_rate: float = 0.,
               creation_delay: float = 0.):

    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.alert_priority = alert_priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert

    self.duration_sound = duration_sound
    self.duration_hud_alert = duration_hud_alert
    self.duration_text = duration_text

    self.alert_rate = alert_rate
    self.creation_delay = creation_delay

    self.start_time = 0.
    self.alert_type = ""
    self.event_type = None

  def __str__(self) -> str:
    return f"{self.alert_text_1}/{self.alert_text_2} {self.alert_priority} {self.visual_alert} {self.audible_alert}"

  def __gt__(self, alert2) -> bool:
    return self.alert_priority > alert2.alert_priority

class NoEntryAlert(Alert):
  def __init__(self, alert_text_2, audible_alert=AudibleAlert.chimeError,
               visual_alert=VisualAlert.none, duration_hud_alert=2.):
    super().__init__("�������Ϸ� ���Ұ�", alert_text_2, AlertStatus.normal,
                     AlertSize.mid, Priority.LOW, visual_alert,
                     audible_alert, .4, duration_hud_alert, 3.)


class SoftDisableAlert(Alert):
  def __init__(self, alert_text_2):
    super().__init__("�ڵ��� ����ּ���", alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.MID, VisualAlert.steerRequired,
                     AudibleAlert.chimeError, .1, 2., 2.),


class ImmediateDisableAlert(Alert):
  def __init__(self, alert_text_2, alert_text_1="�ڵ��� ����ּ���"):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.HIGHEST, VisualAlert.steerRequired,
                     AudibleAlert.chimeWarningRepeat, 2.2, 3., 4.),

class EngagementAlert(Alert):
  def __init__(self, audible_alert=True):
    super().__init__("", "",
                     AlertStatus.normal, AlertSize.none,
                     Priority.MID, VisualAlert.none,
                     audible_alert, .2, 0., 0.),

class NormalPermanentAlert(Alert):
  def __init__(self, alert_text_1, alert_text_2):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.normal, AlertSize.mid,
                     Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),

# ********** alert callback functions **********

def below_steer_speed_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(round(CP.minSteerSpeed * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = "km/h" if metric else "mph"
  return Alert(
    "�ڵ��� ����ּ���",
    "%d %s ���Ͽ����� ������� �Ұ��մϴ�" % (speed, unit),
    AlertStatus.userPrompt, AlertSize.mid,
    Priority.MID, VisualAlert.none, AudibleAlert.none, 0., 0.4, .3)

def calibration_incomplete_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(MIN_SPEED_FILTER * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH))
  unit = "km/h" if metric else "mph"
  return Alert(
    "Ķ���극�̼� ������: %d%%" % sm['liveCalibration'].calPerc,
    "%d %s �̻��� �ӵ��� �����ϼ���" % (speed, unit),
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2)

def no_gps_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  gps_integrated = sm['pandaState'].pandaType in [log.PandaState.PandaType.uno, log.PandaState.PandaType.dos]
  return Alert(
    "GPS ��ȣ ����",
    "ȯ�濡 ������ ������� �������� �����ϼ���" if gps_integrated else "GPS���׳� ��ġ�� �����ϼ���",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=300.)

def wrong_car_mode_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  text = "ũ���� ��� ����"
  if CP.carName == "honda":
    text = "Main Switch Off"
  return NoEntryAlert(text, duration_hud_alert=0.)

def standstill_alert(CP, sm, metric):
  elapsed_time = sm['pathPlan'].standstillElapsedTime
  elapsed_time_min = elapsed_time // 60
  elapsed_time_sec = elapsed_time - (elapsed_time_min * 60)

  if elapsed_time_min == 0:
    return Alert(
      "��� ���� (����ð�: %02d��)" % (elapsed_time_sec),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.5)
  else:
    return Alert(
      "��� ���� (����ð�: %d�� %02d��)" % (elapsed_time_min, elapsed_time_sec),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.5)

EVENTS: Dict[int, Dict[str, Union[Alert, Callable[[Any, messaging.SubMaster, bool], Alert]]]] = {
  # ********** events with no alerts **********

  # ********** events only containing alerts displayed in all states **********

  EventName.debugAlert: {
    ET.PERMANENT: Alert(
      "DEBUG ALERT",
      "",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.startup: {
    ET.PERMANENT: Alert(
      "�������Ϸ� ����غ� �Ǿ����ϴ�",
      "���������� ���� �׻� �ڵ��� ��� ���α��� ��Ȳ�� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 5.),
  },

  EventName.startupMaster: {
    ET.PERMANENT: Alert(
      "���: �� Branch�� �׽�Ʈ���� �ʾҽ��ϴ�",
      "���������� ���� �׻� �ڵ��� ��� ���α��� ��Ȳ�� �ֽ��ϼ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 5.),
  },

  EventName.startupNoControl: {
    ET.PERMANENT: Alert(
      "���ķ ���",
      "���������� ���� �׻� �ڵ��� ��� ���α��� ��Ȳ�� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 5.),
  },

  EventName.startupNoCar: {
    ET.PERMANENT: Alert(
      "���ķ ���: �������� �ʴ� ����",
      "���������� ���� �׻� �ڵ��� ��� ���α��� ��Ȳ�� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 5.),
  },

  EventName.dashcamMode: {
    ET.PERMANENT: Alert(
      "���ķ ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: Alert(
      "������ LKAS ����� ���� �ֽ��ϴ�",
      "�������Ϸ� ����� ���� LKAS�� ������",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.communityFeatureDisallowed: {
    # LOW priority to overcome Cruise Error
    ET.PERMANENT: Alert(
      "Ŀ�´�Ƽ ��� ������",
      "������ �������� Ŀ�´�Ƽ ����� Ȱ��ȭ�ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.carUnrecognized: {
    ET.PERMANENT: Alert(
      "���ķ ���",
      "���ν� ����",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "���� AEB: �浹 ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.stockFcw: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "���� FCW: �浹 ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "�浹 ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.chimeWarningRepeat, 1., 2., 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      "�ڵ��� ����ּ���",
      "������Ż�� �����Ǿ����ϴ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimePrompt, 1., 2., 3.),
  },

  # ********** events only containing alerts that display while engaged **********

  EventName.gasPressed: {
    ET.PRE_ENABLE: Alert(
      "�����߿��� �������Ϸ� �극��ũ �۵��Ұ�",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .0, .0, .1, creation_delay=1.),
  },

  EventName.vehicleModelInvalid: {
    ET.NO_ENTRY: NoEntryAlert("���� �Ű� ���� �ĺ� ����"),
    ET.WARNING: Alert(
      "���� �Ű� ���� �ĺ� ����",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .0, .0, .1),
  },

  EventName.steerTempUnavailableMute: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "������� �Ͻ������� ��Ȱ��ȭ �Ǿ����ϴ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, .2, .2),
  },

  EventName.preDriverDistracted: {
    ET.WARNING: Alert(
      "���λ�Ȳ�� ���Ǹ� ����̼���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.promptDriverDistracted: {
    ET.WARNING: Alert(
      "���λ�Ȳ�� �����ϼ���",
      "�����ֽ� �ʿ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, .1, .1, .1),
  },

  EventName.driverDistracted: {
    ET.WARNING: Alert(
      "���: ������� ��� �����˴ϴ�",
      "������ �����ֽ� �Ҿ�",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarningRepeat, .1, .1, .1),
  },

  EventName.preDriverUnresponsive: {
    ET.WARNING: Alert(
      "�ڵ��� ��ġ�ϼ���: ����͸� ����",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.promptDriverUnresponsive: {
    ET.WARNING: Alert(
      "�ڵ��� ��ġ�ϼ���",
      "������ ����͸� ����",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.driverUnresponsive: {
    ET.WARNING: Alert(
      "���: ������� ��� �����˴ϴ�",
      "������ ����͸� ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.driverMonitorLowAcc: {
    ET.WARNING: Alert(
      "������ �� Ȯ�� ��",
      "������ �� �ν��� �������� �ʽ��ϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .4, 0., 1.5),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� ����� �ϼ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      "��ø���",
      "������� ���� RES��ư�� ��������",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      "���� ������ ���� �ڵ��� �������� ��¦ ��������",
      "�ٸ� ������ �����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      "���� ������ ���� �ڵ��� �������� ��¦ ��������",
      "�ٸ� ������ �����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      "���� ���� ���� ��",
      "�ٸ� ������ �����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1),
  },

  EventName.laneChange: {
    ET.WARNING: Alert(
      "���� ���� ��",
      "�ٸ� ������ �����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1),
  },
  
  EventName.laneChangeManual: {
    ET.WARNING: Alert(
      "���� �������õ� �۵� ��",
      "�ڵ������� �Ͻ� ��Ȱ��ȭ �˴ϴ� ���� �����ϼ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.emgButtonManual: {
    ET.WARNING: Alert(
      "���� ���� ��",
      "",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.driverSteering: {
    ET.WARNING: Alert(
      "������ ���� ������",
      "�ڵ������� �Ͻ������� ���ϵ˴ϴ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .1, .1),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� ������ ��Ż�ϰ� �ֽ��ϴ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.fanMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("�� ���۵�", "�������� �����ϼ���"),
  },

  EventName.cameraMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("ī�޶� ���۵�", "�������� �����ϼ���"),
  },

  EventName.gpsMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("GPS ���۵�", "�������� �����ϼ���"),
  },

  EventName.modeChangeOpenpilot: {
    ET.WARNING: Alert(
      "�������Ϸ� ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeModeOpenpilot, 1., 0, 1.),
  },
  
  EventName.modeChangeDistcurv: {
    ET.WARNING: Alert(
      "����+Ŀ�� ���� ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeModeDistcurv, 1., 0, 1.),
  },
  EventName.modeChangeDistance: {
    ET.WARNING: Alert(
      "����ONLY ���� ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeModeDistance, 1., 0, 1.),
  },
  EventName.modeChangeOneway: {
    ET.WARNING: Alert(
      "��1���� ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeModeOneway, 1., 0, 1.),
  },
  EventName.needBrake: {
    ET.WARNING: Alert(
      "�극��ũ!",
      "�ߵ�����",
      AlertStatus.normal, AlertSize.full,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeWarning2Repeat, .1, .1, .1),
  },
  EventName.standStill: {
    ET.WARNING: standstill_alert,
  },

  # ********** events that affect controls state transitions **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.brakeHold: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("�극��ũ Ȧ�� ��"),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("��ŷ�극��ũ ü�� ��"),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("���� �� ��� ����",
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("���Ƽ�� ũ��� Ȱ��ȭ�ϼ���"),
  },

  EventName.steerTempUnavailable: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "������� �Ͻ������� ��Ȱ��ȭ �Ǿ����ϴ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeWarning1, .4, 2., 3.),
    ET.NO_ENTRY: NoEntryAlert("������� �Ͻ������� ��Ȱ��ȭ �Ǿ����ϴ�",
                              duration_hud_alert=0.),
  },

  EventName.outOfSpace: {
    ET.PERMANENT: Alert(
      "������� ����",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("Out of Storage Space",
                              duration_hud_alert=0.),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: NoEntryAlert("������ �ӵ� ����"),
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      "EON�����κ��� �����͸� ���� ���߽��ϴ�",
      "��ġ�� ����� �ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("EON�����κ��� �����͸� ���� ���߽��ϴ�"),
  },

  EventName.noGps: {
    ET.PERMANENT: no_gps_alert,
  },

  EventName.soundsUnavailable: {
    ET.PERMANENT: NormalPermanentAlert("����Ŀ�� ã�� �� �����ϴ�", "��ġ�� ������ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("����Ŀ�� ã�� �� �����ϴ�"),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: NoEntryAlert("������ �����ֽ� �ſ� �Ҿ�"),
  },

  EventName.overheat: {
    ET.PERMANENT: Alert(
      "�ý����� �����Ǿ����ϴ�",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.SOFT_DISABLE: SoftDisableAlert("�ý����� �����Ǿ����ϴ�"),
    ET.NO_ENTRY: NoEntryAlert("�ý����� �����Ǿ����ϴ�"),
  },

  EventName.wrongGear: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("�� ����̺��尡 �ƴմϴ�"),
  },

  EventName.calibrationInvalid: {
    ET.PERMANENT: NormalPermanentAlert("Ķ���극�̼� ��ȿ���� ����", "��ġ ��ġ ���� �� �� Ķ���극�̼�"),
    ET.SOFT_DISABLE: SoftDisableAlert("Ķ���극�̼� ��ȿ���� ����: ��ġ ��ġ ���� �� �� Ķ���극�̼�"),
    ET.NO_ENTRY: NoEntryAlert("Ķ���극�̼� ��ȿ���� ����: ��ġ ��ġ ���� �� �� Ķ���극�̼�"),
  },

  EventName.calibrationIncomplete: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: SoftDisableAlert("Ķ���극�̼� ���� ��"),
    ET.NO_ENTRY: NoEntryAlert("Ķ���극�̼� ���� ��"),
  },

  EventName.doorOpen: {
    ET.SOFT_DISABLE: SoftDisableAlert("��� �����ֽ��ϴ�"),
    ET.NO_ENTRY: NoEntryAlert("��� �����ֽ��ϴ�"),
  },

  EventName.seatbeltNotLatched: {
    ET.SOFT_DISABLE: SoftDisableAlert("������Ʈ�� ü���ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("������Ʈ�� ü���ϼ���"),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: SoftDisableAlert("ESP ����"),
    ET.NO_ENTRY: NoEntryAlert("ESP ����"),
  },

  EventName.lowBattery: {
    ET.SOFT_DISABLE: SoftDisableAlert("���͸� ����"),
    ET.NO_ENTRY: NoEntryAlert("���͸� ����"),
  },

  EventName.commIssue: {
    ET.SOFT_DISABLE: SoftDisableAlert("���μ��� �� ��� ������ �ֽ��ϴ�"),
    ET.NO_ENTRY: NoEntryAlert("���μ��� �� ��� ������ �ֽ��ϴ�",
                              audible_alert=AudibleAlert.none),
  },

  EventName.processNotRunning: {
    ET.NO_ENTRY: NoEntryAlert("�ý��� ���۵�: ��ġ�� ������ϼ���",
                              audible_alert=AudibleAlert.none),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: SoftDisableAlert("���̴� ����: ������ ������ϼ���"),
    ET.NO_ENTRY : NoEntryAlert("���̴� ����: ������ ������ϼ���"),
  },

  EventName.modeldLagging: {
    ET.SOFT_DISABLE: SoftDisableAlert("���� �� ����"),
    ET.NO_ENTRY : NoEntryAlert("���� �� ����"),
  },

  EventName.posenetInvalid: {
    ET.SOFT_DISABLE: SoftDisableAlert("���� �����ν��� �������� �ʽ��ϴ�"),
    ET.NO_ENTRY: NoEntryAlert("���� �����ν��� �������� �ʽ��ϴ�"),
  },

  EventName.deviceFalling: {
    ET.SOFT_DISABLE: SoftDisableAlert("��ġ�� ����Ʈ ������ �Ҿ��մϴ�"),
    ET.NO_ENTRY: NoEntryAlert("��ġ�� ����Ʈ ������ �Ҿ��մϴ�"),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: SoftDisableAlert("�޸� ����: ��ġ�� ������ϼ���"),
    ET.PERMANENT: NormalPermanentAlert("�޸� ����", "��ġ�� ������ϼ���"),
    ET.NO_ENTRY : NoEntryAlert("�޸� ����: ��ġ�� ������ϼ���",
                               audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.controlsFailed: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("�������� �Ұ�"),
    ET.NO_ENTRY: NoEntryAlert("�������� �Ұ�"),
  },

  EventName.controlsMismatch: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Controls Mismatch"),
  },

  EventName.canError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("CAN ����: CAN ��ȣ�� Ȯ���ϼ���"),
    ET.PERMANENT: Alert(
      "CAN ����: CAN ��ȣ�� Ȯ���ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("CAN ����: CAN ��ȣ�� Ȯ���ϼ���"),
  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("LKAS ����: ������ ������ϼ���"),
    ET.PERMANENT: Alert(
      "LKAS ����: ������ ���� ������ ������ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("LKAS ����: ������ ������ϼ���"),
  },

  EventName.brakeUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("ũ���� ����: ������ ������ϼ���"),
    ET.PERMANENT: Alert(
      "ũ���� ����: ������ ���� ������ ������ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("ũ���� ����: ������ ������ϼ���"),
  },

  EventName.reverseGear: {
    ET.PERMANENT: Alert(
      "���� ���",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=0.5),
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("���� ���"),
    ET.NO_ENTRY: NoEntryAlert("���� ���"),
  },

  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("ũ���� ����"),
  },

  EventName.plannerError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Planner Solution Error"),
    ET.NO_ENTRY: NoEntryAlert("Planner Solution Error"),
  },

  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("�ϳ׽� ���۵�"),
    ET.PERMANENT: NormalPermanentAlert("�ϳ׽� ���۵�", "��ġ�� �����ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("�ϳ׽� ���۵�"),
  },

  EventName.noTarget: {
    ET.IMMEDIATE_DISABLE: Alert(
      "�������Ϸ� ���ۺҰ�",
      "���������� �����ϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.none, .4, 2., 3.),
    ET.NO_ENTRY : NoEntryAlert("���������� �����ϴ�"),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      "�������Ϸ� ���ۺҰ�",
      "������ �ӵ��� �����ϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.none, .4, 2., 3.),
  },

  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      "�ӵ��� �ʹ� �����ϴ�",
      "�� �۵��� ���� ������ �ӵ��� ���߼���",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeWarning2Repeat, 2.2, 3., 4.),
    ET.NO_ENTRY: Alert(
      "�ӵ��� �ʹ� �����ϴ�",
      "������ ���� ������ �ӵ��� ���߼���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeError, .4, 2., 3.),
  },

  EventName.lowSpeedLockout: {
    ET.PERMANENT: Alert(
      "ũ���� ����: ������ ���� ������ ������ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("ũ���� ����: ������ ������ϼ���"),
  },

}
