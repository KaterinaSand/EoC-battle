from tools.terms import ENV
from tools.distances import euclidean_distance

class FightEvent:
    def __init__(self, fight_handler):
        self._fight_handler = fight_handler
        self.subscriptions = {}
        self.checkers = {}

    def add_checker(self, name, la_check, la_gen):
        self.checkers[name] = (la_check, la_gen)
        self.subscriptions[name] = []

    def add_subscriptions(self, name, data):
        self.subscriptions[name].append(data)

    def gen_fighters_checker(self, la_checker):
        fight_handler = self._fight_handler
        def _checker(event, receiver):
            for event_item in fight_handler.get_battle_fighters():
                if event_item.is_dead:
                    continue
                if receiver == event_item:
                    continue
                if not event_item.coordinates:
                    continue

                if la_checker(event_item, event, receiver):
                    return event_item

        return _checker

    def setup(self):
        fight_handler = self._fight_handler
        fighters = fight_handler.fighters

        self.add_checker('time', 
            lambda event, receiver: fight_handler.current_game_time >= event['data']['time'],
            lambda event, receiver, res: {'time': event['data']['time']})

        self.add_checker('idle',
            lambda event, receiver: (event['data']['id'] in fighters and
                fighters[event['data']['id']]._state.get('action') == 'idle'),
            lambda event, receiver, res: {'id': event['data']['id']})

        self.add_checker('enemy_in_my_firing_range', 
            self.gen_fighters_checker(
                lambda event_item, event, receiver: (
                    euclidean_distance(receiver.coordinates, event_item.coordinates)  - event_item.size / 2 <= receiver.firing_range)
                    and receiver.player_id != event_item.player_id
                ),
            lambda event, receiver, res: {'id': res.id})

        self.add_checker('death',
            lambda event, receiver: fighters.get(event['data']['id']) and fighters.get(event['data']['id']).is_dead,
            lambda event, receiver, res: {'id': event['data']['id']})

        self.add_checker('unit_landed',
            self.gen_fighters_checker(
                lambda event_item, event, receiver: event_item.fflag('landed') and event['data']['craft_id'] == event_item.craft_id),
            lambda event, receiver, res: res.info)

    def check(self):
        fight_handler = self._fight_handler

        from pprint import pprint
        pprint(self.subscriptions)
        print('-'*10)
        pprint(list(map(lambda item: [item.id, item.craft_id, item.fflag('landed')], fight_handler.fighters.values())))

        for event_name, subscriptions in self.subscriptions.items():
            if not subscriptions:
                continue

            (check_function, data_function) = self.checkers[event_name]

            for event in subscriptions[:]:
                receiver = fight_handler.fighters[event['receiver_id']]
                res = check_function(event, receiver)
                if res:
                    data_to_event = data_function(event, receiver, res)
                    data_to_event.update({
                        ENV.DATA: fight_handler.get_env_data(),
                        ENV.MY_DATA: fight_handler.get_my_data(event['receiver_id'])
                    })
                    receiver.send_event(lookup_key=event['lookup_key'],
                                        data=data_to_event)
                    subscriptions.remove(event)



