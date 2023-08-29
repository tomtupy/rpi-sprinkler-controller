# rpi-sprinkler-controller
Sprinkler Controller for Raspberry Pi

`NEW_RELIC_ENVIRONMENT=production NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program python sprinkler.py`

<img width="843" alt="Screenshot 2023-08-28 205755" src="https://github.com/tomtupy/rpi-sprinkler-controller/assets/7709362/6e92b63b-c3ca-49b8-94d2-f82207d1f0f4">

## Failsafe Circuit
Because this program controls a live irrigation system, a failure has the potential to rack up a big water bill and/or cause a flood.
Pretty much any failure mode will result in the GPIO pin getting stuck in HIGH or LOW.
A good solution here is to enable power to the relay board only if the program is pulsing a pin between HIGH and LOW at some interval. If the signal stays HIGH or LOW past the expected interval, the circuit will time out and cut power to the relay board (and therefore all solenoids controlling water will lose power).

A good circuit for this is described here: https://forums.raspberrypi.com/viewtopic.php?t=185076#p1171118
![image](https://github.com/tomtupy/rpi-sprinkler-controller/assets/7709362/644275bf-c846-47d3-ad8e-e08f6f007e2a)

The output of the circuit keeps a master relay open if the input is being pulsed. The master relay controls power to the relay board.

## Operation
### Run a zone
Example: Run zone 14 for 1 minute
```
mutation {
  runZone(zone: 14, durationMins: 1) {
    zoneList {
      zone
      state
    }
    relayBoardEnabled
  }
}
```

### Reset board state
```
mutation {
  reset {
    zoneList {
      zone
      state
    }
  }
}
```

### Disable/Enable Relay board
These mutations control whether the failsafe keep-alive signal is generated
```
mutation {
  enable {
    zoneList {
      zone
      state
    }
    relayBoardEnabled
  }
}
```

```
mutation {
  disable {
    zoneList {
      zone
      state
    }
    relayBoardEnabled
  }
}
```

### Get Status
```
query {
  getStatus {
    zoneList {
      zone
      state
      requestedOnMins
      elapsedOnSecs
    }
  }  
}
```
response:
```
{
  "data": {
    "getStatus": {
      "zoneList": [
        {
          "elapsedOnSecs": null,
          "requestedOnMins": null,
          "state": "OFF",
          "zone": 1
        },
...
        {
          "elapsedOnSecs": 13,
          "requestedOnMins": 1,
          "state": "ON",
          "zone": 14
        },
...
      ]
    }
  }
}
```
