# Appdaemon-apps
A place for me to store apps used for automations in Home assistant

SmartCarCharger:
This system is setup to calculate the cheapest prices for charging an EV in my case a Tesla.
It is possible to set an end time for charging or not having any is also a valid option.
In the case of a high charge request (>92%) chargedBy time is a requirement as the car will be set to allways charge the last hour before wanting it ready to avoid leaving the car at 100% charge

The system is setup with the TeslaMate for most of the data required as well as a ESPHome tesla BLE (https://github.com/yoziru/esphome-tesla-ble) for activating the charging.

Energy prices are setup for using this integration: https://github.com/MTrab/stromligning if using something else, code should be updated
All arguments should be added in the apps.yaml file fx. chargeSwitch:         switch.tesla_ble_034d60_charger_switch

Following helpers needs to be added to Homeassistant:
Input boolean - For enabling/disabling the feature arg(enableSmartCharge)
Input number - For setting min. wanted charge level, the system will charge to this level before planning arg(minCharge)
Input number - For setting Max price, this will be in cents (øre) arg(maxPrice)
Input datetime - For setting a chargedBy datetime, when would you like the charging to finish arg(chargedBy)
Input boolean - For disable chargedBy datetime, if it does not matter when it finishes charging, just use cheapest prices arg(disableChargedBy)
