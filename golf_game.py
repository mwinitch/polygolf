import os
import time
import signal
import numpy as np
import sympy
import json
import argparse
import logging
from remi import start
from golf_app import GolfApp
import constants
from utils import *
from players.default_player import Player as DefaultPLayer



class GolfGame:
    def __init__(self, player_list, args):
        self.use_gui = not(args.no_gui)
        self.do_logging = not(args.disable_logging)
        if not self.use_gui:
            self.use_timeout = not(args.disable_timeout)
        else:
            self.use_timeout = False

        self.logger = logging.getLogger(__name__)
        # create file handler which logs even debug messages
        if self.do_logging:
            self.logger.setLevel(logging.DEBUG)
            self.log_dir = args.log_path
            if self.log_dir:
                os.makedirs(self.log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(self.log_dir, 'debug.log'), mode="w")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter('%(message)s'))
            fh.addFilter(MainLoggingFilter(__name__))
            self.logger.addHandler(fh)
            result_path = os.path.join(self.log_dir, "results.log")
            rfh = logging.FileHandler(result_path, mode="w")
            rfh.setLevel(logging.INFO)
            rfh.setFormatter(logging.Formatter('%(message)s'))
            rfh.addFilter(MainLoggingFilter(__name__))
            self.logger.addHandler(rfh)
        else:
            if args.log_path:
                self.logger.setLevel(logging.INFO)
                result_path = args.log_path
                self.log_dir = os.path.dirname(result_path)
                if self.log_dir:
                    os.makedirs(self.log_dir, exist_ok=True)
                rfh = logging.FileHandler(result_path, mode="w")
                rfh.setLevel(logging.INFO)
                rfh.setFormatter(logging.Formatter('%(message)s'))
                rfh.addFilter(MainLoggingFilter(__name__))
                self.logger.addHandler(rfh)
            else:
                self.logger.setLevel(logging.ERROR)
                self.logger.disabled = True

        if args.seed == 0:
            args.seed = None
            self.logger.info("Initialise random number generator with no seed")
        else:
            self.logger.info("Initialise random number generator with {} seed".format(args.seed))
        
        self.rng = np.random.default_rng(args.seed)

        self.golf = Golf(args.map, self.logger)
        self.players = []
        self.player_names = []
        self.skills = []
        self.player_states = []
        self.played = []
        self.curr_locs = []
        self.scores = []
        self.next_player = None

        self.time_taken = []
        self.timeout_count = []
        self.error_count = []

        self.processing_turn = False
        self.end_message_printed = False
        
        # start(GolfApp, address=args.address, port=args.port, start_browser=not(args.no_browser), update_interval=0.5, userdata=(self, args.automatic))
        self.__add_players(player_list)
        self.next_player = self.__assign_next_player()

        if self.use_gui:
            start(GolfApp, address=args.address, port=args.port, start_browser=not(args.no_browser), update_interval=0.5, userdata=(self, args.automatic))
        else:
            self.logger.debug("No GUI flag specified")
        

    def set_app(self, golf_app):
        self.golf_app = golf_app
    
    def __add_players(self, player_list):
        player_count = dict()
        for player_name in player_list:
            if player_name not in player_count:
                player_count[player_name] = 0
            player_count[player_name] += 1

        count_used = {k: 0 for k in player_count}
        for player_name in player_list:
            if player_name in constants.possible_players:
                if player_name.lower() == "d":
                    player_class = DefaultPLayer
                    base_player_name = "Default Player"
                else:
                    player_class = eval("G{}_Player".format(player_name))
                    base_player_name = "Group {}".format(player_name)
                count_used[player_name] += 1
                if player_count[player_name] == 1:
                    self.__add_player(player_class, "{}".format(base_player_name))
                else:
                    self.__add_player(player_class, "{}.{}".format(base_player_name, count_used[player_name]))
            else:
                self.logger.error("Failed to insert player {} since invalid player name provided.".format(player_name))

    def __add_player(self, player_class, player_name):
        if player_name not in self.player_names:
            skill = self.rng.integers(constants.min_skill,constants.max_skill+1)
            self.logger.info("Adding player {} from class {} with skill {}".format(player_name, player_class.__module__, skill))
            player = player_class(skill, self.rng, self.__get_player_logger(player_name))
            self.players.append(player)
            self.player_names.append(player_name)
            self.skills.append(skill)
            self.player_states.append("NP")
            self.played.append([])
            self.curr_locs.append(self.golf.start)
            self.scores.append(0)
            self.time_taken.append([])
            self.timeout_count.append(0)
            self.error_count.append(0)
        else:
            self.logger.error("Failed to insert player as another player with name {} exists.".format(player_name))

    def __get_player_logger(self, player_name):
        player_logger = logging.getLogger("{}.{}".format(__name__, player_name))

        if self.do_logging:
            player_logger.setLevel(logging.INFO)
            # add handler to self.logger with filtering
            player_fh = logging.FileHandler(os.path.join(self.log_dir, '{}.log'.format(player_name)), mode="w")
            player_fh.setLevel(logging.DEBUG)
            player_fh.setFormatter(logging.Formatter('%(message)s'))
            player_fh.addFilter(PlayerLoggingFilter(player_name))
            self.logger.addHandler(player_fh)
        else:
            player_logger.setLevel(logging.ERROR)
            player_logger.disabled = True

        return player_logger
    
    def is_game_ended(self):
        return np.all([x in constants.end_player_states for x in self.player_states])

    """Fix here"""
    def __game_end(self):
        if not self.end_message_printed and self.is_game_ended():
            self.end_message_printed = True
            self.logger.info("Game ended as each player finished playing")
            

    
    def __assign_next_player(self):
        # randomly select among valid players
        valid_players = [i for i,s in enumerate(self.player_states) if s not in constants.end_player_states]
        if valid_players:
            # return valid_players[self.rng.integers(0, valid_players.size)]
            return valid_players[0]
        return None

    def __turn_end(self):
        self.processing_turn = False

        self.next_player = self.__assign_next_player()
        if self.next_player:
            self.logger.debug("Next turn {}".format(self.player_names[self.next_player]))

    def play_all(self):
        if not self.is_game_ended():
            self.logger.debug("Playing all turns")
            while not self.is_game_ended():
                self.play(run_stepwise=False, do_update=False)
            if self.use_gui:
                self.golf_app.update_score_table()
            self.__game_end()

    def play(self, run_stepwise=False, do_update=True):
        if not self.processing_turn:
            if not self.is_game_ended():
                if self.player_states[self.next_player] in constants.end_player_states:
                    self.logger.debug("Can't pass to the {}, as the player's game finished".format(self.player_names[self.next_player]))
                    self.next_player = self.__assign_next_player()
                    self.logger.debug("Assigned new player {}".format(self.player_names[self.next_player]))

                self.logger.debug("Current turn {}".format(self.player_names[self.next_player]))

                self.processing_turn = True
                self.player_states[self.next_player] = "P"
                self.time_taken[self.next_player].append([])

            else:
                self.__game_end()
                return

        if run_stepwise:
            pass_next = self.__step(self.next_player, do_update)
            if pass_next:
                self.__turn_end()

        else:
            pass_next = False
            while not pass_next:
                pass_next = self.__step(self.next_player, do_update=False)
            if do_update and self.use_gui:
                self.golf_app.update_score_table()
            self.__turn_end()

    def __check_action(self, returned_action):
        if not returned_action:
            return False
        is_valid = False
        if isiterable(returned_action) and count_iterable(returned_action) == 2:
            if np.all([sympy.simplify(x).is_real for x in returned_action]):
                is_valid = True

        return is_valid

    def __step(self, player_idx, do_update=True):
        pass_next = False
        if self.player_states[player_idx] in ["F", "S"] or self.scores[player_idx] >= constants.max_tries:
            pass_next = True
        else:
            self.scores[player_idx] += 1
            try:
                if self.use_timeout:
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(constants.timeout)
                try:
                    start_time = time.time()
                    returned_action = self.players[player_idx].play(golf_map=self.golf.golf_map, target=self.golf.target, curr_loc=self.curr_locs[player_idx])
                    if self.use_timeout:
                        signal.alarm(0)      # Clear alarm
                except TimeoutException:
                    self.logger.error("Timeout {} since {:.3f}s reached.".format(self.player_names[player_idx], constants.timeout))
                    returned_action = None
                    self.timeout_count[player_idx] += 1
                step_time = time.time() - start_time
                self.time_taken[player_idx].append(step_time)
            except Exception as e:
                self.logger.error(e, exc_info=True)
                returned_action = None
                self.error_count[player_idx] += 1

            is_valid_action = self.__check_action(returned_action)
            if is_valid_action:
                distance, angle = returned_action
                segment_air, segment_land, final_point, admissible, reached_target = self.__move(distance, angle, player_idx)
                if admissible:
                    self.curr_locs[player_idx] = final_point            
                self.played[player_idx].append((segment_air, segment_land, final_point, admissible, reached_target))
                if reached_target:
                    self.logger.info("{} reached Target with score {}".format(self.player_names[player_idx], self.scores[player_idx]))
                    self.player_states[player_idx] = "S"                
                    pass_next = True
                elif self.scores[player_idx] >= constants.max_tries:
                    self.logger.info("{} failed since it used {} max tries".format(self.player_names[player_idx], constants.max_tries))
                    self.player_states[player_idx] = "F"
                    pass_next = True
            else:
                self.logger.info("{} failed since provided invalid action {}".format(self.player_names[player_idx], returned_action))
                self.player_states[player_idx] = "F"
                pass_next = True
        
        if do_update and self.use_gui:
            self.golf_app.plot(segment_air, segment_land, admissible)
            self.golf_app.update_score_table()

        return pass_next

        

    def __move(self, distance, angle, player_idx):
        curr_loc = self.curr_locs[player_idx]
        actual_distance = self.rng.normal(distance, distance/self.skills[player_idx])
        actual_angle = self.rng.normal(angle, 1/(2*self.skills[player_idx]))
        self.logger.debug("{} provided Distance: {}, Angle: {}".format(self.player_names[player_idx], distance, angle))
        self.logger.debug("Observed Distance: {}, Angle: {}".format(actual_distance,actual_angle))

        if distance <= constants.max_dist+self.skills[player_idx] and distance >= constants.min_putter_dist:
            landing_point = sympy.Point2D(curr_loc.x+actual_distance*np.cos(actual_angle), curr_loc.y+actual_distance*np.sin(actual_angle))
            final_point = sympy.Point2D(curr_loc.x+(1.+constants.extra_roll)*actual_distance*np.cos(actual_angle), curr_loc.y+(1.+constants.extra_roll)*actual_distance*np.sin(actual_angle))
        
        elif distance < constants.min_putter_dist:
            self.logger.debug("Using Putter as provided distance {} less than {}".format(distance, constants.min_putter_dist))
            landing_point = curr_loc
            final_point = sympy.Point2D(curr_loc.x+actual_distance*np.cos(actual_angle), curr_loc.y+actual_distance*np.sin(actual_angle))
        
        else:
            self.logger.debug("Provide invalid distance {}, distance should be < {}".format(distance, constants.max_dist+self.skills[player_idx]))
            landing_point = curr_loc
            final_point = curr_loc
        
        segment_air = sympy.geometry.Segment2D(curr_loc, landing_point)
        segment_land = sympy.geometry.Segment2D(landing_point, final_point)

        if segment_land.distance(self.golf.target) <= constants.target_radius:
            reached_target = True
            final_point = segment_land.projection(self.golf.target)
            segment_land = sympy.geometry.Segment2D(landing_point, final_point)
        else:
            reached_target = False
        
        admissible = False
        if self.golf.golf_map.encloses(segment_land):
            admissible = True
        
        reached_target = reached_target and admissible
        return segment_air, segment_land, final_point, admissible, reached_target
    
     



class Golf:
    def __init__(self, map_filepath, logger) -> None:
        self.logger = logger
        if not os.path.exists(map_filepath):
            self.logger.error("Using default map as couldn't find {}".format(map_filepath))
            map_filepath = constants.default_map
        
        self.logger.info("Map file loaded: {}".format(map_filepath))
        with open(map_filepath, "r") as f:
            json_obj = json.load(f)
        self.start = sympy.geometry.Point2D(*json_obj["start"])
        self.target = sympy.geometry.Point2D(*json_obj["target"])
        self.golf_map = sympy.Polygon(*json_obj["map"])
        


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", "-m", default=constants.default_map, help="Path to map json file")
    parser.add_argument("--automatic", action="store_true", help="Start playing automatically in GUI mode")
    parser.add_argument("--seed", "-s", type=int, default=2021, help="Seed used by random number generator, specify 0 to use no seed and have different random behavior on each launch")
    parser.add_argument("--port", type=int, default=8080, help="Port to start")
    parser.add_argument("--address", "-a", type=str, default="127.0.0.1", help="Address")
    parser.add_argument("--no_browser", "-nb", action="store_true", help="Disable browser launching in GUI mode")
    parser.add_argument("--no_gui", "-ng", action="store_true", help="Disable GUI")
    parser.add_argument("--log_path", default="log", help="Directory path to dump log files, filepath if disable_logging is false")
    parser.add_argument("--disable_timeout", "-time", action="store_true", help="Disable Timeout in non GUI mode")
    parser.add_argument("--disable_logging", action="store_true", help="Disable Logging, log_path becomes path to file")
    parser.add_argument("--players", "-p", default=["d"], nargs="+", help="List of players space separated")
    args = parser.parse_args()
    player_list = tuple(args.players)
    del args.players

    if args.disable_logging:
        if args.log_path == "log":
            args.log_path = "results.log"
    
    golf_game = GolfGame(player_list, args)