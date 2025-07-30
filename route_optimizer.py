# route_optimizer.py

import math
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from google.protobuf.duration_pb2 import Duration

def haversine(a, b):
    R = 6371  # Raio da Terra em km
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def optimize_route(clients, strategy="PATH_CHEAPEST_ARC", time_limit_ms=1000):
    """
    clients: [ {"id":str, "lat":float, "lon":float}, ... ]
    strategy: nome de FirstSolutionStrategy (string)
    time_limit_ms: tempo máximo de busca local (ms)
    retorna: [id1, id2, ...] na ordem ótima
    """
    n = len(clients)
    # Monta matriz de distâncias em metros
    M = [[0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j: continue
            a = (clients[i]["lat"], clients[i]["lon"])
            b = (clients[j]["lat"], clients[j]["lon"])
            M[i][j] = int(haversine(a, b) * 1000)

    mgr = pywrapcp.RoutingIndexManager(n, 1, 0)
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

    sol = routing.SolveWithParameters(search_params)
    # Extrai a sequência de IDs
    route = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        route.append(clients[mgr.IndexToNode(idx)]["id"])
        idx = sol.Value(routing.NextVar(idx))
    return route
