from .base import BaseItemActions, euclidean_distance
from .exceptions import ActionValidateError
from tools import find_route, straighten_route, is_coordinates
from sub_items import VerticalRocketSubItem, HealSubItem
from tools.terms import OPERATION, ROLE, FEATURE

import logging
logger = logging.getLogger()

class MineActions(BaseItemActions):
    def actions_init(self):
        return {
            'wait': self.action_wait,
            'detonate': self.action_detonate,
        }

    def action_wait(self, data):
        for enemy in self._fight_handler.fighters.values():
            if enemy.is_dead:
                return

            if enemy.player_id == self._item.player_id:
                continue

            if enemy.role != ROLE.UNIT:
                continue

            distance_to_enemy = euclidean_distance(enemy.coordinates, self._item.coordinates)

            if distance_to_enemy <= self._item.firing_range:
                self._item.detonate()
                break

        return {
            'action': 'idle'
        }

    def action_detonate(self, data):
        self._item.detonator_timer()
        return {
            'action': 'detonate'
        }
        

class FlagActions(BaseItemActions):

    def actions_init(self):
        return {}

    def commands_init(self):
        return {
            'rocket': self.send_rocket,
            'heal': self.send_heal,
            'power': self.send_power,
        }

    def send_rocket(self, data):
        flagman = self._item
        if flagman.use_operation(OPERATION.ROCKET):
            flagman.add_sub_item(VerticalRocketSubItem(flagman, data['coordinates']))

    def send_heal(self, data):
        flagman = self._item
        if flagman.use_operation(OPERATION.HEAL):
            flagman.add_sub_item(HealSubItem(flagman, data['coordinates']))

    def send_power(self, data):
        flagman = self._item
        if flagman.use_operation(OPERATION.POWER):
            flagman.add_sub_item(PowerSubItem(flagman, data['coordinates']))

class CraftActions(BaseItemActions):

    def actions_init(self):
        return {
            'land_units': self.action_land_units,
        }

    def action_land_units(self, data):
        if self._item.land_unit():
            #print('LAND', self._item.craft_id, self._item.amount_units_in)
            return {
                'action': 'land_units'
            }
        else:
            #print('DONE LANDING', self._item.craft_id, self._item.amount_units_in)
            return self._idle()

    def commands_init(self):
        return {
            'attack': self.forward_by('attack'),
            'move': self.forward_by('move'),
            'moves': self.forward_by('moves'),
            'teleport': self.forward_command_by('teleport'),
        }

    def forward_by(self, command):
        def _forwarded(data):
            unit = self._fight_handler.fighters[data['by']]

            # TODO: check if unit from Craft
            # craft = self._item

            unit.method_set_action(command, data, from_self=False)  
        return _forwarded

    def forward_command_by(self, command):
        def _forwarded(data):
            unit = self._fight_handler.fighters[data['by']]

            # TODO: check if unit from Craft
            # craft = self._item

            unit.method_command(command, data, from_self=False)  
        return _forwarded

    def forward_do_attack(self, data):
        unit = self._fight_handler.fighters[data['by']]

        # TODO: check if unit from Craft
        # craft = self._item

        unit.method_set_action('attack', data, from_self=False)


class UnitActions(BaseItemActions):
    def __init__(self, *args, **kwargs):
        self._route = []
        self._last_map_hash = 0
        self._last_destination_point = (0, 0)

        super().__init__(*args, **kwargs)

    def actions_init(self):
        actions = super().actions_init()
        actions.update({
            'move': self.action_move,
            'moves': self.action_moves
        })
        return actions

    def commands_init(self):
        return {
            'teleport': self.trans_action('teleport')
        }

    def one_actions_init(self):
        return {
            'teleport': self.do_teleport
        }


    def do_teleport(self, data):
        if not self._item.has_feature(FEATURE.TELEPORT):
            return
        if self._item.used_feature(FEATURE.TELEPORT):
            return
        self._item.use_feature(FEATURE.TELEPORT)
        coordinates = data.get('coordinates')
        self._item.set_coordinates(coordinates)

    def action_attack(self, data):
        enemy = self._fight_handler.fighters.get(data['id'])
        if enemy is None:
            return  # WTF
        distance_to_enemy = euclidean_distance(enemy.coordinates, self._item.coordinates)
        item_firing_range = self._item.firing_range
        if (distance_to_enemy - enemy.size / 2) > item_firing_range:
            return self._move(enemy.coordinates)
        return self._shot(enemy)

    def action_move(self, data):
        coordinates = data.get('coordinates')
        coordinates = self._fight_handler.adjust_coordinates(*coordinates)
        return self._move(coordinates)

    def action_moves(self, data):
        steps = data.get('steps')
        if not len(steps):
            return self._stop()
        coordinates = steps[0]
        coordinates = self._fight_handler.adjust_coordinates(*coordinates)
        ret = self._move(coordinates, stop_then=False)
        if ret:
            return ret

        data['steps'] = steps[1:]
        return self.action_moves(data)

    def check_or_create_route(self, destination_point):
        if (self._fight_handler.map_hash != self._last_map_hash or
                not self._route or
                self._last_destination_point != tuple(destination_point)):
            self.calculate_route(destination_point)
            self._last_map_hash = self._fight_handler.map_hash
            self._last_destination_point = tuple(destination_point)

    def _stop(self):
        return self._idle()

    def process_near_turns(self, distance):
        intermediate_point = tuple(self._item.coordinates)
        next_point = self._route[0]
        while self._route and euclidean_distance(intermediate_point, next_point) < distance:
            distance -= euclidean_distance(intermediate_point, next_point)
            intermediate_point = self._route.pop(0)
            next_point = self._route[0] if self._route else next_point
        return next_point, intermediate_point

    def _move(self, destination_point, stop_then=True):
        self.check_or_create_route(destination_point)
        if not self._route:
            return stop_then and self._stop()
        frame_distance = self._item.speed * self._fight_handler.GAME_FRAME_TIME
        start_point = tuple(self._item.coordinates)
        # We on the end
        if len(self._route) == 1 and start_point == self._route[0]:
            return stop_then and self._stop()
        next_point, current_point = self.process_near_turns(frame_distance)
        if not self._route:
            self._item.set_coordinates(current_point)
            # without it we will not stop
            self._route.append(current_point)
            return {'action': 'move',
                    'from': start_point,
                    'to': current_point}
        distance = euclidean_distance(current_point, next_point)
        new_point = (
            current_point[0] + (frame_distance / distance) * (next_point[0] - current_point[0]),
            current_point[1] + (frame_distance / distance) * (next_point[1] - current_point[1]))

        self._item.set_coordinates(new_point)
        return {'action': 'move',
                'from': start_point,
                'to': new_point}

    def calculate_route(self, end_point):
        current_point = self._item.coordinates
        grid_scale = self._fight_handler.GRID_SCALE
        cell_shift = self._fight_handler.CELL_SHIFT
        current_cell = (int(round((current_point[0] - cell_shift) * grid_scale)),
                        int(round((current_point[1] - cell_shift) * grid_scale)))
        end_cell = (int(round((end_point[0] - cell_shift) * grid_scale)),
                    int(round((end_point[1] - cell_shift) * grid_scale)))
        # A-star search
        cell_route = find_route(self._fight_handler.map_grid,
                                self._fight_handler.map_graph,
                                current_cell, end_cell)
        cut_cell_route = straighten_route(self._fight_handler.map_grid, cell_route)
        self._route = [((c[0] / grid_scale) + cell_shift, (c[1] / grid_scale) + cell_shift)
                       for c in cut_cell_route]

    def validate_move(self, action, data):
        if not is_coordinates(data.get("coordinates")):
            raise ActionValidateError("Wrong coordinates {}".format(data.get("coordinates")))

    def validate_moves(self, action, data):
        for coordinates in data.get('steps'):
            if not is_coordinates(coordinates):
                raise ActionValidateError("Wrong coordinates {}".format(coordinates))

    def validate_attack(self, action, data):
        enemy = self._fight_handler.fighters.get(data['id'])
        if enemy.is_dead:
            raise ActionValidateError("The enemy is dead")
        if enemy.player['id'] == self._item.player['id']:
            raise ActionValidateError("Can not attack own item")
