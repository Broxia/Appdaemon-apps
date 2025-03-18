import hassapi as hass
import pandas as pd
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import math

class SmartCarCharger(hass.Hass):
  def initialize(self):
    self._chargeSwitch         = self.args["chargeSwitch"] 
    self._wakeCar              = self.args["wakeCar"] 
    self._cableState           = self.args["cableState"] 
    self._carState             = self.args["carState"] 
    self._remainingTimeSensor  = self.args["remainingTime"] 
    self._soc                  = self.args["soc"] 
    self._socLimit             = self.args["socLimit"] 
    self._location             = self.args["location"] 
    self._enableSmartCharge    = self.args["enableSmartCharge"] 
    self._maxPrice             = self.args["maxPrice"] 
    self._disableChargedBy     = self.args["disableChargedBy"] 
    self._chargedBy            = self.args["chargedBy"] 
    self._energyPricesToday    = self.args["energyPricesToday"] 
    self._energyPricesTomorrow = self.args["energyPricesTomorrow"] 
    self._minCharge            = self.args["minCharge"] 

    self._chargeHandles = []
    self._initiateHandle = ""
    self._priceHandle = ""

    self._pricePrognosis = pd.DataFrame()
    self._remainingTime = 0
    self._initatedCharging = False
    
    self.listen_state(self.cableStateChanged, self._cableState)
    self.listen_state(self.enableStateChanged, self._enableSmartCharge)
    self.listen_state(self.carStateChanged, self._carState, new="charging")
    self.listen_state(self.parameterChanged, self._socLimit)
    self.listen_state(self.parameterChanged, self._disableChargedBy)
    self.listen_state(self.parameterChanged, self._chargedBy)
    self.listen_state(self.parameterChanged, self._maxPrice)
    self.listen_state(self.parameterChanged, self._soc)
    self.listen_state(self.parameterChanged, self._minCharge)
    self.listen_state(self.parameterChanged, self._location, new = "home")

    self.run_daily(self.setUpdateForTomorrowsPrices, "01:00:00")

    self.cableStateChanged(self._cableState, "None", "off", self.get_state(self._cableState), "") #Check state at startup

  def setUpdateForTomorrowsPrices(self, kwargs=""):
    if(self.timer_running(self._priceHandle)):
      self.cancel_timer(self._priceHandle)

    stateTomorrow = self.get_state(self._energyPricesTomorrow, attribute="all")
    dataTomorrow = stateTomorrow['attributes']
    tomorrowAvailableTime = pd.to_datetime(dataTomorrow.get("available_at")) + timedelta(minutes=5)
    self._priceHandle = self.run_at(self.handleEnergyPriceData, datetime.fromisoformat(str(tomorrowAvailableTime)))
    
  def cableStateChanged(self, entity, attribute, old, new, kwargs):
    if(new == "on"):
      if(self.get_state(self._enableSmartCharge) == "on" and self.get_state(self._location) == "home"):
        self.startSmartCharge()
      else: #Either not home or smart charge not enabled
        self.log("Start charging, not home or instant charging")
        self.startCharging()
    else:
      self.clearHandles()
      self._pricePrognosis.iloc[0:0]

  def enableStateChanged(self, entity, attribute, old, new, kwargs):
    if(new == "off" and self.get_state(self._cableState) == "on"):   
      self.startCharging() #Smart charge turned off and cable attached, start charging
      self.clearHandles()
    elif(new == "on" and self.get_state(self._cableState) == "on" and self.get_state(self._location) == "home"): #Smart charge turned on, cable attached and home, calculate times
      self.startSmartCharge()

  def handleEnergyPriceData(self, kwargs=""):
    if self.isSmartChargeRequired():
      self.log("Smartcharging and energy prices updated, Recalculating!")
      self.startSmartCharge()

  def parameterChanged(self, entity, attribute, old, new, kwargs):
    if(self.isSmartChargeRequired()):
      if entity != self._soc or (entity == self._soc and ((int(new) == 88) or int(new) == int(float(self.get_state(self._minCharge))))):
        #cable plugged in, smart charge enable and at home. Recalculate!
        self.log("Smartcharging and change happened to {e}, Recalculating!".format(e=entity))
        self.startSmartCharge()

  def carStateChanged(self, entity, attribute, old, new, kwargs):
    if self.shouldDisableCharging(): 
      self.run_in(self.chargingSanityCheck, 30)
  
  def chargingSanityCheck(self, kwargs):
    if self.shouldDisableCharging():
      self.log("Stopping charging started i did not initate")
      self.stopCharging()

  def shouldDisableCharging(self):
    if self._initatedCharging == False and self.get_state(self._location) == "home" and (float(self.get_state(self._soc)) < (float(self.get_state(self._socLimit)) - 2) and self.get_state(self._enableSmartCharge) == "on"):
      return True
    else:
      return False

  def isSmartChargeRequired(self):
    if(self.get_state(self._cableState) == "on" and self.get_state(self._enableSmartCharge) == "on" and self.get_state(self._location) == "home"):
      return True
    else:
      return False

  def updateEnergyPriceData(self, kwargs = ""):
    self.log("Updating energy service data for SmartCharger")
    self._pricePrognosis.iloc[0:0]
    stateToday = self.get_state(self._energyPricesToday, attribute="all")
    stateTomorrow = self.get_state(self._energyPricesTomorrow, attribute="all")
    dataToday = stateToday['attributes']
    dataTomorrow = stateTomorrow['attributes']
    
    tomorrow_valid = self.get_state(self._energyPricesTomorrow)
    
    pricePrognosisToday = pd.DataFrame.from_dict(dataToday.get('prices'))

    #If tomorrows prices available, include them otherwise plan when to update 
    if tomorrow_valid == "on":
      pricePrognosisTomorrow = pd.DataFrame.from_dict(dataTomorrow.get('prices'))
      self._pricePrognosis = pd.concat([pricePrognosisToday, pricePrognosisTomorrow], ignore_index=True)
    else:
      self._pricePrognosis = pricePrognosisToday
      self.setUpdateForTomorrowsPrices()

    #Convert times to DateTime
    self._pricePrognosis['start'] = pd.to_datetime(self._pricePrognosis['start'])
    
  def calculateCheapestHours(self, kwargs = ""):
    self.updateEnergyPriceData()
    #remove all indexes in the past
    cheapestHours = self._pricePrognosis[self._pricePrognosis.start + timedelta(hours=1) > self.get_now()]
    #Remove all indexes below defined max price
    maxPrice = float(self.get_state(self._maxPrice))/ 100
    cheapestHours = cheapestHours[cheapestHours.price < maxPrice]
    #Sort by value
    cheapestHours.sort_values(by=['price', 'start'], inplace=True)
    # self.log(cheapestHours)
    return cheapestHours

  def determineChargingTimes(self, kwargs = ""):
    cheapestHours = self.calculateCheapestHours()
    
    fullHours = math.floor(self._remainingTime)
    minutes = math.ceil((self._remainingTime - fullHours) * 60)
    self.log("Remaining time = " + str(fullHours) + ":" + str(minutes))

    data = {
      "start": [],
      "end":   []
    }

    if self.get_state(self._disableChargedBy) == "off": #Remove values if Charged By time enabled
      chargedByTime = self.get_state(self._chargedBy)

      #remove datapoints outside charged by
      if self.now_is_between("00:00:00", chargedByTime):
        #Charged by today
        chargedByDate = date.today()
      else:
        #Charged by tomorrow
        chargedByDate = date.today() + timedelta(days=1)
      chargedBy = datetime.combine(chargedByDate, datetime.strptime(chargedByTime, '%H:%M:%S').time(), tzinfo=ZoneInfo('Europe/Copenhagen'))

      cheapestHours = cheapestHours[cheapestHours.start < chargedBy]
      #If time to finish charging is less than available, just charge now
      if fullHours + 1 > cheapestHours.size:
        self.log("Will not complete charging within required time, start charging now")
        self.startCharging()
        return

      if int(self.get_state(self._socLimit)) > 90: #If SoC limit is over 90%, ensure the last hour charged is up to leaving time, no matter the price
        start = chargedBy - timedelta(hours=1)
        end = chargedBy
        data["start"].append(start)
        data["end"].append(end)  
        fullHours -= 1 
        chargedBy = start
        cheapestHours = cheapestHours[cheapestHours.start < start]
        self.log("socLimit > 90%, start = {start}, end = {end}".format(start = start, end = end))

    cheapestHours = cheapestHours.reset_index(drop=True)

    i = 0
    while i < fullHours and i < len(cheapestHours.index):
      start = cheapestHours.loc[i].start
      end = start + timedelta(hours=1)
      if start < self.get_now() and end > self.get_now(): #If timezone is started
        start = self.get_now() + timedelta(seconds=30)
        delta = end - start
        minutes += delta.total_seconds() /60

      if self.get_state(self._disableChargedBy) == "off" and end > chargedBy:
        end = chargedBy
        delta = end - start
        minutes += delta.total_seconds() /60
      
      data["start"].append(start)
      data["end"].append(end)
      if(minutes >= 60):
        fullHours += 1
        minutes -= 60
      i += 1

    while minutes > 0 and i < len(cheapestHours.index):
      start = cheapestHours.loc[i].start
      end = start + timedelta(minutes=minutes)
      if start < self.get_now(): # if timezone is started
        start = self.get_now() + timedelta(seconds=30)
        end = start + timedelta(minutes=minutes)
        if end > cheapestHours.loc[i].start.to_pydatetime() + timedelta(hours=1): #If timezone ends before required minutes
          end = cheapestHours.loc[i].start.to_pydatetime() + timedelta(hours=1)
        if self.get_state(self._disableChargedBy) == "off" and end > chargedBy:
          end = chargedBy
  
        delta = end - start
        minutes -= delta.total_seconds() /60  

        i += 1 #add 1 to i as that is used for our index
      else:
        minutes = 0

      data["start"].append(start)
      data["end"].append(end)

    chargeTimes = pd.DataFrame(data)
    chargeTimes.sort_values(by='start', inplace=True)
    chargeTimes = chargeTimes.reset_index(drop=True)

    for i in range(len(chargeTimes)):
      start = chargeTimes.loc[i].start
      end   = chargeTimes.loc[i].end
      # self.log("Charging time determined from {start} to {end}".format(start=start, end=end))
      if i+1 < len(chargeTimes):
        nextStart = chargeTimes.loc[i+1].start
      else:
        nextStart = "None"
      if i != 0:
        prevEnd = chargeTimes.loc[i-1].end
      else:
        prevEnd = "None"
      self.chargeScheduler(start=start, end=end, nextStart=nextStart, prevEnd=prevEnd)    
      
  def chargeScheduler(self, start, end, nextStart, prevEnd):
    if(prevEnd == "None" or start != prevEnd):
      self.log("Scheduled charging start at {start}".format(start=start))
      if self.isToday(start=start) and self.now_is_between(start.strftime("%H:%M:%S"), end.strftime("%H:%M:%S")): 
        self.log("Start time has passed, starting now")
        self.startCharging()
      else:
        self._chargeHandles.append(self.run_at(self.startCharging, datetime.fromisoformat(str(start))))
    if(nextStart == "None"):
      self.log("Scheduled charging will be recalculated at {end}".format(end=end))
      self._chargeHandles.append(self.run_at(self.startSmartCharge, datetime.fromisoformat(str(end))))
    elif( nextStart != end):
      self.log("Scheduled charging ends at {end}".format(end=end))
      self._chargeHandles.append(self.run_at(self.stopCharging, datetime.fromisoformat(str(end))))

  def isToday(self, start, kwargs = ""):
    return datetime.today().strftime('%Y-%m-%d') == start.strftime("%Y-%m-%d")

  def clearHandles(self, kwargs = ""):
    for h in self._chargeHandles:
        if(self.timer_running(h)):
          self.cancel_timer(h)
    self._chargeHandles.clear()
    if(self.timer_running(self._initiateHandle)):
      self.cancel_timer(self._initiateHandle)

  def startSmartCharge(self, kwargs = ""):
    if self.get_state(self._cableState) != "on":
      self.log("Smartcharge started but cable not inserted, cancelling")
      return
    self.log("Starting smart charge of car")
    self.startCharging()
    if(self.timer_running(self._initiateHandle)):
      self.cancel_timer(self._initiateHandle)
    if float(self.get_state(self._socLimit)) - float(self.get_state(self._soc)) < 2.0: #If SoC is less than 2% under the limit, just charge
      self.log("SOC less than 2% from limit, will just charge!")
      self.startCharging()
    elif(float(self.get_state(self._soc)) >= float(self.get_state(self._minCharge))): #If soc larger than min charge calculate otherwise charge until min soc
      self._initiateHandle = self.run_in(self.enableCharging, 60) #Delayed to allow calculation of remaining time
  
  def enableCharging(self, kwargs = ""):
    self._remainingTime = float(self.get_state(self._remainingTimeSensor))
    
    if self._remainingTime == 0 and self.get_state(self._soc) < self.get_state(self._socLimit): #Calculation not successfull, allow another cycle
      self.startSmartCharge()
      self.log("Time = 0, restarting calculation")
      return

    self.stopCharging()
    self.clearHandles()
    self.determineChargingTimes()

  def startCharging(self, kwargs = ""):
    self.log("Starting charging")

    self.call_service("button/press", entity_id = self._wakeCar)
    self.run_in(self.turnOnCharger, 5) #Allowing 5 seconds for car to wake up
    self._initatedCharging = True

  def turnOnCharger(self, kwargs = ""):
    self.turn_on(self._chargeSwitch) 

  def stopCharging(self, kwargs = ""):
    self.log("Stopping charging")
    self.call_service("button/press", entity_id = self._wakeCar)
    self.run_in(self.turnOffCharger, 5) #Allowing 5 seconds for car to wake up

  def turnOffCharger(self, kwargs = ""):
    self.turn_off(self._chargeSwitch) 
    self._initatedCharging = False