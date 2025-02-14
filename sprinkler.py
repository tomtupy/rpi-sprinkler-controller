from typing import Final, List
import newrelic.agent
import logging
import time
from threading import Thread, Lock
from enum import Enum
from ariadne.explorer import ExplorerGraphiQL
from flask import Flask, request, jsonify
from ariadne import QueryType, MutationType, load_schema_from_path, make_executable_schema, graphql_sync
from graphql import GraphQLError
from gpiozero import DigitalOutputDevice
import queue

MAX_ZONE_RUNTIME_MINS = 60
logging.basicConfig()
logging.root.setLevel(logging.NOTSET)
logging.basicConfig(level=logging.NOTSET)
NR_APPLICATION = newrelic.agent.application()

# Synchronization
LOOP_INSTRUCTON_PROCESSING_LOCK = Lock()
LOOP_THREAD_INSTRUCTION_QUEUE = queue.Queue()
LOOP_THEAD_RESPONSE_QUEUE = queue.Queue()

# ---- GPIO ----
class GpioLoopInstructions(Enum):
    RESET = 0
    RUN_ZONE = 1
    ENABLE = 2
    DISABLE = 3
    GET_STATUS = 4

class GpioLoopInstruction():
   def __init__(self, instruction: GpioLoopInstructions, zone: int = None, durationMins: int = None):
      self.type = instruction
      self.zone = zone
      self.durationMins = durationMins

PIN_ENABLE = DigitalOutputDevice(pin=21, active_high=True, initial_value=False)
ZONE_TO_PIN_MAP: Final = {
   1: 11,
   2: 19,
   3: 26,
   4: 13,
   5: 27,
   6: 12,
   7: 8,
   8: 22,
   9: 6,
   10: 7,
   11: 16,
   12: 9,
   13: 20,
   14: 5,
   15: 10,
   16: 25
}

# GPIO Loop Thread
class BoardNotReadyException(Exception):
    pass

class GpioLoopThread(Thread):
   def __init__(self):
      self.zone_pin_map = dict.fromkeys(ZONE_TO_PIN_MAP.keys(), None)
      for zone_id in ZONE_TO_PIN_MAP.keys():
         self.zone_pin_map[zone_id] = DigitalOutputDevice(pin=ZONE_TO_PIN_MAP[zone_id], active_high=False, initial_value=False)
      self.is_enabled = True
      self.running_zone = None
      self.running_zone_requested_on_mins = None
      self.running_zone_start_time = None
      self.running_zone_end_time = None
      Thread.__init__(self)

   @newrelic.agent.background_task()
   def run(self):
      logging.info("GPIO Loop Started...")
      while True:
         # get instruction from queue
         with LOOP_INSTRUCTON_PROCESSING_LOCK:
            if (not LOOP_THREAD_INSTRUCTION_QUEUE.empty()):
               try:
                  instruction = LOOP_THREAD_INSTRUCTION_QUEUE.get_nowait()
                  if (isinstance(instruction, GpioLoopInstruction)):
                     logging.info(f"Processing instruction {instruction.type}")
                     newrelic.agent.record_custom_event('handle_instruction', {'instruction_type': str(instruction.type)}, NR_APPLICATION)

                     # enable/disable
                     if (instruction.type is GpioLoopInstructions.ENABLE):
                        self.is_enabled = True
                        LOOP_THEAD_RESPONSE_QUEUE.put(self.getZoneStatusResponse())
                     elif (instruction.type is GpioLoopInstructions.DISABLE):
                        self.is_enabled = False
                        LOOP_THEAD_RESPONSE_QUEUE.put(self.getZoneStatusResponse())
                     
                     # Run a zone
                     elif (instruction.type is GpioLoopInstructions.RUN_ZONE):
                        self.handleZoneRunInstruction(instruction)
                        LOOP_THEAD_RESPONSE_QUEUE.put(self.getZoneStatusResponse())

                     # reset board
                     elif (instruction.type is GpioLoopInstructions.RESET):
                        self.handleResetInstruction()
                        LOOP_THEAD_RESPONSE_QUEUE.put(self.getZoneStatusResponse())
   
                     # get status
                     elif (instruction.type is GpioLoopInstructions.GET_STATUS):
                        LOOP_THEAD_RESPONSE_QUEUE.put(self.getZoneStatusResponse())
                     
               except Exception as e:
                  # return the exception in the response
                  LOOP_THEAD_RESPONSE_QUEUE.put(e)
            
               LOOP_THREAD_INSTRUCTION_QUEUE.task_done()
               LOOP_THREAD_INSTRUCTION_QUEUE.queue.clear() # just in case
         
         if (self.is_enabled):
            # Toggle keep alive signal for failsafe board
            pin_enable_char = "▲" if PIN_ENABLE.is_active else "▼"
            print("\rEnable signal: {state}".format(state=pin_enable_char), end="")
            if PIN_ENABLE.is_active is True:
                PIN_ENABLE.off()
            else:
                PIN_ENABLE.on()
            newrelic.agent.record_custom_metric('keep_alive_signal', PIN_ENABLE.value, NR_APPLICATION)

         # check running zone
         if (self.running_zone is not None):
            if (int(time.time()) >= self.running_zone_end_time or int(time.time()) >= self.running_zone_start_time + (MAX_ZONE_RUNTIME_MINS * 60)):
               self.handleResetInstruction()

         time.sleep(0.5)
       

   def handleResetInstruction(self):
      logging.debug(f"Attempting to turn off all zones")
      for zone in self.zone_pin_map.values():
          zone.off()
      zone_statuses = [zone.is_active for zone in self.zone_pin_map.values()]
      if (not any(zone_statuses)):
         # success
         self.running_zone = None
         self.running_zone_requested_on_mins = None
         self.running_zone_start_time = None
         self.running_zone_end_time = None
         return
      # pin states unknown if off() failed
      raise GraphQLError(f"Unable to turn off zones!")

   def handleZoneRunInstruction(self, instruction):
      if (isinstance(instruction.zone, int)
            and instruction.zone in ZONE_TO_PIN_MAP.keys()
            and isinstance(instruction.durationMins, int)
            and instruction.durationMins > 0
            and instruction.durationMins <= MAX_ZONE_RUNTIME_MINS):

         self.handleResetInstruction()
         self.zone_pin_map[instruction.zone].on()
         logging.debug(f"Turning on zone {instruction.zone} at pin {self.zone_pin_map[instruction.zone]}")
         self.running_zone = instruction.zone
         self.running_zone_requested_on_mins = instruction.durationMins
         self.running_zone_start_time = int(time.time())
         self.running_zone_end_time = self.running_zone_start_time + (instruction.durationMins * 60)
         logging.info(f"Running zone {instruction.zone} for {instruction.durationMins}")
         return
      else:
         raise GraphQLError(f"Invalid zone/duration params: {instruction.zone} {instruction.durationMins}")

   def pinStateStr(self, pinState):
      if (pinState is True):
         return "ON"
      elif (pinState is False):
         return "OFF"
      elif (pinState is None):
         return "UNKNOWN"
   
   def getZoneStatusResponse(self):
      zoneList = []
      for zonePin in self.zone_pin_map.items():
         zone = zonePin[0]
         pin = zonePin[1]
         zoneState = self.pinStateStr(pin.is_active)
         zoneStatus = { "zone": zone, "state": zoneState }
         if (self.running_zone == zone):
            zoneStatus["requestedOnMins"] = self.running_zone_requested_on_mins
            zoneStatus["elapsedOnSecs"] = int(time.time()) - self.running_zone_start_time
         zoneList.append(zoneStatus)
      return { "zoneList": zoneList, "relayBoardEnabled": self.is_enabled}


LOOP_THREAD = GpioLoopThread()



# ---- WEB/API ----
# Web - GraphQL
type_defs = load_schema_from_path("schema.graphql")
query = QueryType()
mutation = MutationType()

# resolvers
@query.field("getStatus")
def getStatus(*_):
   with LOOP_INSTRUCTON_PROCESSING_LOCK:
      LOOP_THREAD_INSTRUCTION_QUEUE.put(GpioLoopInstruction(GpioLoopInstructions.GET_STATUS))
   return processResponse()

@mutation.field("reset")
def reset(_, info):
   with LOOP_INSTRUCTON_PROCESSING_LOCK:
      LOOP_THREAD_INSTRUCTION_QUEUE.put(GpioLoopInstruction(GpioLoopInstructions.RESET))
   return processResponse()

@mutation.field("enable")
def reset(_, info):
   with LOOP_INSTRUCTON_PROCESSING_LOCK:
      LOOP_THREAD_INSTRUCTION_QUEUE.put(GpioLoopInstruction(GpioLoopInstructions.ENABLE))
   return processResponse()

@mutation.field("disable")
def reset(_, info):
   with LOOP_INSTRUCTON_PROCESSING_LOCK:
      LOOP_THREAD_INSTRUCTION_QUEUE.put(GpioLoopInstruction(GpioLoopInstructions.DISABLE))
   return processResponse()

@mutation.field("runZone")
def runZone(_, info, zone, durationMins):
   with LOOP_INSTRUCTON_PROCESSING_LOCK:
      LOOP_THREAD_INSTRUCTION_QUEUE.put(GpioLoopInstruction(GpioLoopInstructions.RUN_ZONE, zone, durationMins))
   return processResponse()

def processResponse():
   response = LOOP_THEAD_RESPONSE_QUEUE.get(True, 10)
   LOOP_THEAD_RESPONSE_QUEUE.task_done()
   LOOP_THEAD_RESPONSE_QUEUE.queue.clear() # just in case
   if (isinstance(response, Exception)):
      raise response
   return response


# Create executable schema
schema = make_executable_schema(type_defs, [query, mutation])

# initialize flask app
app = Flask(__name__)
explorer_html = ExplorerGraphiQL().html(None)

# Create a GraphQL Playground UI for the GraphQL schema
@app.route("/graphql", methods=["GET"])
def graphql_playground():
  # On GET request serve the GraphQL explorer.
    # You don't have to provide the explorer if you don't want to
    # but keep on mind this will not prohibit clients from
    # exploring your API using desktop GraphQL explorer app.
    return explorer_html, 200

# Create a GraphQL endpoint for executing GraphQL queries
@app.route("/graphql", methods=["POST"])
def graphql_server():
   # GraphQL queries are always sent as POST
    data = request.get_json()

    # Note: Passing the request to the context is optional.
    # In Flask, the current request is always accessible as flask.request
    success, result = graphql_sync(
        schema,
        data,
        context_value={"request": request},
        debug=app.debug
    )

    status_code = 200 if success else 400
    return jsonify(result), status_code


# ---- Main ----
if __name__ == "__main__":
   from waitress import serve
   LOOP_THREAD.start()
   serve(app, host="0.0.0.0", port=8080)
