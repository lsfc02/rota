import math
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from google.protobuf.duration_pb2 import Duration

def haversine(a, b):
    R = 6371  # raio da Terra em km
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def optimize_route(
    clients,
    strategy: str = "PATH_CHEAPEST_ARC",
    time_limit_ms: int = 1000,
    start_index: int = 0
) -> list[str]:
    """
    clients:       [ {"id":str, "lat":float, "lon":float}, ... ]
    strategy:      FirstSolutionStrategy (string)
    time_limit_ms: tempo máximo de busca local (ms)
    start_index:   índice (0-based) do cliente de partida na lista `clients`
    retorna:       [id1, id2, ...] na ordem ótima, começando em clients[start_index]
    """

    n = len(clients)
    # Monta matriz de distâncias em metros
    M = [[0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            a = (clients[i]["lat"],  clients[i]["lon"])
            b = (clients[j]["lat"],  clients[j]["lon"])
            M[i][j] = int(haversine(a, b) * 1000)

    # Manager com start_index variável
    mgr = pywrapcp.RoutingIndexManager(n, 1, start_index)
    routing = pywrapcp.RoutingModel(mgr)

    transit_cb = routing.RegisterTransitCallback(
        lambda i, j: M[mgr.IndexToNode(i)][mgr.IndexToNode(j)]
    )
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    # Parâmetros de busca
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    # Estratégia inicial
    search_params.first_solution_strategy = getattr(
        routing_enums_pb2.FirstSolutionStrategy,
        strategy
    )
    # Metaheurística de refinamento
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    # Limite de tempo — usa um Duration
    dur = Duration()
    dur.FromMilliseconds(time_limit_ms)
    search_params.time_limit.CopyFrom(dur)

    # Resolve
    sol = routing.SolveWithParameters(search_params)
    if sol is None:
        # Sem solução, retorna ordem original de ids
        return [c["id"] for c in clients]

    # Extrai sequência de IDs
    route = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        node = mgr.IndexToNode(idx)
        route.append(clients[node]["id"])
        idx = sol.Value(routing.NextVar(idx))

    return route
