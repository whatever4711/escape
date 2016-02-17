# Copyright (c) 2014 Balazs Nemeth
#
# This file is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This file is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with POX. If not, see <http://www.gnu.org/licenses/>.

from collections import defaultdict
import sys
import logging, copy

import networkx as nx

import UnifyExceptionTypes as uet

# these are needed for the modified NetworkX functions.
from heapq import heappush, heappop
from itertools import count

log = logging.getLogger("mapping")
# log.setLevel(logging.DEBUG)
if not log.getEffectiveLevel():
  logging.basicConfig(format='%(levelname)s:%(name)s:%(message)s')
  log.setLevel(logging.DEBUG)


def subtractNodeRes (current, substrahend, maximal, link_count=1):
  """
  Subtracts the subtrahend nffg_elements.NodeResource object from the current.
  Note: only delay component is not subtracted, for now we neglect the load`s
  influence on the delay. Link count identifies how many times the bandwidth
  should be subtracted. Throw exception if any field of the 'current' would 
  exceed 'maximal' or get below zero.
  """
  attrlist = ['cpu', 'mem', 'storage', 'bandwidth']  # delay excepted!
  if reduce(lambda a, b: a or b, (current[attr] is None for attr in attrlist)):
    raise uet.BadInputException(
      "Node resource components should always be given",
      "One of %s`s components is None" % str(current))
  if not reduce(lambda a, b: a and b,
            (0 <= current[attr] - substrahend[attr] <= maximal[attr] 
             for attr in attrlist if
             attr != 'bandwidth' and substrahend[attr] is not None)):
    raise uet.InternalAlgorithmException("Node resource got below zero, or "
                                         "exceeded the maximal value!")
  if substrahend['bandwidth'] is not None:
    if not 0 <= current['bandwidth'] - link_count * substrahend['bandwidth'] <=\
       maximal['bandwidth']:
      raise uet.InternalAlgorithmException("Internal bandwidth cannot get below "
                                           "zero, or exceed the maximal value!")
  for attr in attrlist:
    k = 1
    if attr == 'bandwidth':
      k = link_count
    if substrahend[attr] is not None:
      current[attr] -= k * substrahend[attr]
  return current

def retrieveFullDistMtx (dist, G_full):
  # this fix access latency is used by CarrierTopoBuilder.py
  log.debug("Retrieving path lengths of SAP-s excepted because "
            "of cutting...")
  access_lat = 0.5
  for u in G_full:
    if G_full.node[u].type == 'SAP':
      u_switch_id = "-".join(tuple(u.split("-")[:1] + u.split("-")[-4:]))
      for v in G_full:
        if u == v:
          dist[u][v] = 0
        elif G_full.node[v].type == 'SAP':
          v_switch_id = "-".join(tuple(v.split("-")[:1] + \
                                       v.split("-")[-4:]))
          dist[u][v] = 2 * access_lat + dist[u_switch_id][v_switch_id]
          dist[v][u] = 2 * access_lat + dist[v_switch_id][u_switch_id]
        else:
          dist[u][v] = access_lat + dist[u_switch_id][v]
          dist[v][u] = access_lat + dist[v][u_switch_id]
  return dist


def shortestPathsInLatency (G_full, enable_shortest_path_cache, 
                            enable_network_cutting=False):
  """Wrapper function for Floyd`s algorithm to calculate shortest paths
  measured in latency, using also nodes` forwarding latencies.
  Modified source code taken from NetworkX library.
  HACK: if enable_network_cutting=True, then all the SAP-s are cut from the 
  network and their distances are recalculated based on where they are 
  connected, which is determined by their ID-s. Its goal is to descrease the 
  running time of Floyd. This hack can only be used if the substrate network is
  generated by CarrierTopoBuilder.py
  """
  # dictionary-of-dictionaries representation for dist and pred
  # use some default dict magic here
  # for dist the default is the floating point inf value
  dist = defaultdict(lambda: defaultdict(lambda: float('inf')))
  
  if enable_network_cutting:
    G = copy.deepcopy(G_full)
    for n,d in G.nodes(data=True):
      if d.type == 'SAP':
        G.remove_node(n)
  else:
    G = G_full
  filename = "shortest_paths_cut.txt" if enable_network_cutting \
             else "shortest_paths.txt"
  if enable_shortest_path_cache:
    try:
      with open(filename) as sp:
        log.debug("Reading previously calculated shortest paths...")
        for line in sp:
          line = line.split(" ")
          dist[line[0]][line[1]] = float(line[2])
      if enable_network_cutting:
        return dict(retrieveFullDistMtx(dist, G_full))
    except IOError:
      log.warn("No input %s found, calculating shortest paths..."%filename)
    except ValueError:
      raise uet.BadInputException("Bad format in shortest_paths.txt",
                                  "In every line: src_id dst_id "
                                  "<<float distance in ms>>")
  
  for u in G:
    if G.node[u].type != 'SAP':
      dist[u][u] = G.node[u].resources['delay']
    else:
      dist[u][u] = 0
  try:
    for u, v, d in G.edges(data=True):
      e_weight = d.delay
      dist[u][v] = min(e_weight, dist[u][v])
  except KeyError as e:
    raise uet.BadInputException("Edge attribure(s) missing " + str(e),
                                "{'delay': VALUE}")
  try:
    for w in G:
      if G.node[w].type != 'SAP':
        for u in G:
          for v in G:
            if dist[u][v] > dist[u][w] + G.node[w].resources['delay'] + dist[w][
              v]:
              dist[u][v] = dist[u][w] + G.node[w].resources['delay'] + dist[w][
                v]
              dist[v][u] = dist[v][w] + G.node[w].resources['delay'] + dist[w][
                u]
            if u == v:
              break
  except KeyError as e:
    raise uet.BadInputException("",
      "Node attribute missing %s {'delay': VALUE}" % e)
  if enable_shortest_path_cache:
    # write calclated paths to output for later use.
    log.debug("Saving calculated shorest paths to %s."%filename)
    sp = open(filename, "w")
    for u in G:
      for v in G:
        sp.write(" ".join((u, v, str(dist[u][v]), "\n")))
    sp.close()
  
  if enable_network_cutting:
    return dict(retrieveFullDistMtx(dist, G_full))
  else:
    return dict(dist)


def shortestPathsBasedOnEdgeWeight (G, source, target=None, cutoff=None):
  """Taken and modified from NetworkX source code,
  the function originally 'was single_source_dijkstra',
  now it returns the key edge data too.
  """
  if source == target:
    return {source: [source]}, {source: []}
  push = heappush
  pop = heappop
  dist = {}  # dictionary of final distances
  paths = {source: [source]}  # dictionary of paths
  # dictionary of edge key lists of corresponding paths
  edgekeys = {source: []}
  seen = {source: 0}
  c = count()
  fringe = []  # use heapq with (distance,label) tuples
  push(fringe, (getattr(G.node[source], 'weight', 0), next(c), source))
  while fringe:
    (d, _, v) = pop(fringe)
    if v in dist:
      continue  # already searched this node.
    dist[v] = d
    if v == target:
      break
    # for ignore,w,edgedata in G.edges_iter(v,data=True):
    # is about 30% slower than the following
    edata = []
    for w, keydata in G[v].items():
      minweight, edgekey = min(((dd.weight, k) for k, dd in keydata.items()),
                               key=lambda t: t[0])
      edata.append((w, edgekey, {'weight': minweight}))

    for w, ekey, edgedata in edata:
      vw_dist = dist[v] + getattr(G.node[w], 'weight', 0) + edgedata['weight']
      if cutoff is not None:
        if vw_dist > cutoff:
          continue
      if w in dist:
        if vw_dist < dist[w]:
          raise ValueError('Contradictory paths found:', 'negative weights?')
      elif w not in seen or vw_dist < seen[w]:
        seen[w] = vw_dist
        push(fringe, (vw_dist, next(c), w))
        paths[w] = paths[v] + [w]
        edgekeys[w] = edgekeys[v] + [ekey]
  return paths, edgekeys


class MappingManager(object):
  """Administrates the mapping of links and VNFs
  TODO: Connect subchain and chain requirements, controls dynamic objective
  function parametrization based on where the mapping process is in an
  (E2E) chain.
  TODO: Could handle backtrack functionality, if other possible mappings
  are also given (to some different structure)"""

  def __init__ (self, net, req, chains, overall_highest_delay):
    self.log = log.getChild(self.__class__.__name__)
    self.log.setLevel(log.getEffectiveLevel())
    # list of tuples of mapping (vnf_id, node_id)
    self.vnf_mapping = []
    # SAP mapping can be done here based on their names
    try:
      for vnf, dv in req.network.nodes_iter(data=True):
        if dv.type == 'SAP':
          sapname = dv.name
          sapfound = False
          for n, dn in net.network.nodes_iter(data=True):
            if dn.type == 'SAP':
              if dn.name == sapname:
                self.vnf_mapping.append((vnf, n))
                sapfound = True
                break
          if not sapfound:
            self.log.error("No SAP found in network with name: %s" % sapname)
            raise uet.MappingException(
              "No SAP found in network with name: %s. SAPs are mapped "
              "exclusively by their names." % sapname,
              backtrack_possible = False)
    except AttributeError as e:
      raise uet.BadInputException("Node data with name %s" % str(e),
                                  "Node data not found")
    
    # same graph structure as the request, edge data stores the mapped path
    self.link_mapping = nx.MultiDiGraph()

    # bandwidth is not yet summed up on the links
    # AND possible Infra nodes and DYNAMIC links are not removed
    self.req = req
    # all chains are included, not only SAP-to-SAPs
    self.chains = chains
    
    # the delay value which is considered to be infinite (although it should be
    # a constant not to zero out the latency component of objective function 
    # calculation)
    self.overall_highest_delay = overall_highest_delay
    
    # chain - subchain pairing, stored in a bipartie graph
    self.chain_subchain = nx.Graph()
    for c in chains:
      if c['delay'] is None:
        c['delay'] = self.overall_highest_delay
    self.chain_subchain.add_nodes_from(
      (c['id'], {'avail_latency': c['delay'], 'permitted_latency': c['delay']}) 
      for c in chains)
    
  def getIdOfChainEnd_fromNetwork (self, _id):
    """
    SAPs are mapped by their name, NOT by their ID in the network/request
    graphs. If the chain is between VNFs, those must be already mapped.
    Input is an ID from the request graph. Return -1 if the node is not
    mapped.
    """
    ret = -1
    for v, n in self.vnf_mapping:
      if v == _id:
        ret = n
        break
    return ret

  def addChain_SubChainDependency (self, subcid, chainids, subc, link_ids):
    """Adds a link between a subchain id and all the chain ids that are
    contained subcid. If the first element of subc is a SAP add its network 
    pair to last_used_host attribute. 
    (at this stage, only SAPs are inside the vnf_mapping list)
    'subchain' attribute of a subchain data dictionary 
    is a list of (vnf1,vnf2,linkid) tuples where the subchain goes.
    """
    # TODO: not E2E chains are also in self.chains, but we don`t find
    # subchains for them, so their latency is not checked, the not E2E
    # chain nodes in this graph always stay the same so far.
    self.chain_subchain.add_node(subcid,
                                 last_used_host=self.getIdOfChainEnd_fromNetwork(
                                   subc[0]),
                                 subchain=zip(subc[:-1], subc[1:], link_ids))
    if len(chainids) == 0:
      self.chain_subchain.add_edge(self.max_input_chainid, subcid)
    for cid in chainids:
      if cid > self.max_input_chainid:
        raise uet.InternalAlgorithmException(
          "Invalid chain identifier given to MappingManager!")
      else:
        self.chain_subchain.add_edge(cid, subcid)

  def getLocalAllowedLatency (self, subchain_id, vnf1=None, vnf2=None,
       linkid=None):
    """
    Checks all sources/types of latency requirement, and identifies
    which is the strictest. The smallest 'maximal allowed latency' will be
    the strictest one. We cannot use paths with higher latency value than
    this one.
    The request link is ordered vnf1, vnf2. This reqlink is part of
    subchain_id subchain.
    This function should only be called on SG links.
    """
    # if there is latency requirement on a request link
    link_maxlat = float("inf")
    if vnf1 is not None and vnf2 is not None and linkid is not None:
      if self.req.network[vnf1][vnf2][linkid].type != 'SG':
        raise uet.InternalAlgorithmException(
          "getLocalAllowedLatency  function should only be called on SG links!")
      if hasattr(self.req.network[vnf1][vnf2][linkid], 'delay'):
        if self.req.network[vnf1][vnf2][linkid].delay is not None:
          link_maxlat = self.req.network[vnf1][vnf2][linkid].delay
    try:
      # find the strictest chain latency which applies to this link
      chain_maxlat = float("inf")
      for c in self.chain_subchain.neighbors_iter(subchain_id):
        if c > self.max_input_chainid:
          raise uet.InternalAlgorithmException(
            "Subchain-subchain connection is not allowed in chain-subchain "
            "bipartie graph!")
        elif self.chain_subchain.node[c]['avail_latency'] < chain_maxlat:
          chain_maxlat = self.chain_subchain.node[c]['avail_latency']

      if min(chain_maxlat, link_maxlat) > self.overall_highest_delay:
        raise uet.InternalAlgorithmException("Local allowed latency should"
        " never exceed the overall_highest_delay")
      return min(chain_maxlat, link_maxlat)

    except KeyError as e:
      raise uet.InternalAlgorithmException(
        "Bad construction of chain-subchain bipartie graph!")

  def isVNFMappingDistanceGood (self, vnf1, vnf2, n1, n2):
    """
    Mapping vnf2 to n2 shouldn`t be further from n1 (vnf1`s host) than
    the strictest latency requirement of all the links between vnf1 and vnf2
    """
    # this equals to the min of all latency requirements (req link local OR 
    # remaining E2E) that is given for any SGHop between vnf1 and vnf2.
    max_permitted_vnf_dist = float("inf")
    for i, j, linkid, d in self.req.network.edges_iter([vnf1], data=True,
                                                       keys=True):
      if self.req.network[i][j][linkid].type != 'SG':
        self.log.warn(
          "There is a not SG link left in the Service Graph, but now it "
          "didn`t cause a problem.")
        continue
      if j == vnf2:
        # i,j are always vnf1,vnf2
        for c, chdata in self.chain_subchain.nodes_iter(data=True):
          if 'subchain' in chdata.keys():
            if (vnf1, vnf2, linkid) in chdata['subchain']:
              # TODO: The colored_req is saved now!!!!!!!!!!!
              # there is only one subchain which contains this
              # reqlink. (link -> chain mapping is not necessary
              # anywhere else, a structure only for realizing this
              # checking effectively seems not useful enough)
              lal = self.getLocalAllowedLatency(c, vnf1, vnf2, linkid)
              subcend = self.\
                        getIdOfChainEnd_fromNetwork(chdata['subchain'][-1][1])
              if self.shortest_paths_lengths[n2][subcend] > \
                 self.getLocalAllowedLatency(c):
                # NOTE: we compare to remaining E2E latency to the minimal path
                # length required until only subchain end, which is less strict 
                # than the actual E2E chain end in general. And used latency
                # between n1 and n2 is further omitted. But still some bad cases
                # can be filtered here.
                self.log.debug("Potential node mapping was too far from chain "
                         "end because of remaining E2E latency requirement")
                return False
              if lal < max_permitted_vnf_dist:
                max_permitted_vnf_dist = lal
              break
    if self.shortest_paths_lengths[n1][n2] > max_permitted_vnf_dist:
      self.log.debug("Potential node mapping was too far from last host because"
                     " of link or remaining E2E latency requirement!")
      return False
    else:
      return True

  def updateChainLatencyInfo (self, subchain_id, used_lat, last_used_host):
    """Updates how much latency does the mapping process has left which
    applies for this subchain.
    """
    for c in self.chain_subchain.neighbors_iter(subchain_id):
      # feasibility already checked by the core algorithm
      self.chain_subchain.node[c]['avail_latency'] -= used_lat
      new_avail_lat = self.chain_subchain.node[c]['avail_latency']
      permitted = self.chain_subchain.node[c]['permitted_latency']
      if new_avail_lat > 1.01*permitted or \
         new_avail_lat <= -0.01*permitted:
        raise uet.InternalAlgorithmException("MappingManager error: End-to-End"
         " available latency cannot exceed maximal permitted or got below zero!")
    self.chain_subchain.node[subchain_id]['last_used_host'] = last_used_host

  def addShortestRoutesInLatency (self, sp):
    """Shortest paths are between physical nodes. These are needed to
    estimate the importance of laltency in the objective function.
    """
    self.shortest_paths_lengths = sp

  def setMaxInputChainId (self, maxcid):
    """Sets the maximal chain ID given by the user. Every chain with lower
    ID-s are given by the user, higher ID-s are subchains generated by
    the preprocessor.
    """
    # Give a spare chain ID for all the best effort subchains, so connect all
    # the subchains to this (self.max_input_chainid) chain in the helper graph
    self.max_input_chainid = maxcid
    self.chain_subchain.add_node(self.max_input_chainid, 
                                {'avail_latency': self.overall_highest_delay, 
                                'permitted_latency': self.overall_highest_delay})
    # we can't use the same ID-s for the output chains, because they will be 
    # splitted into pieces.
    self.max_output_chainid = self.max_input_chainid + 1

  def addReqLink_ChainMapping (self, colored_req):
    """
    SGHop -> E2E chain mapping is required to calculate the splitted EdgeReqs 
    for the lower layer orchestration algorithm. The graph should be deepcopied
    because the preprocessor changes it!
    """
    self.colored_req = copy.deepcopy(colored_req)

  def getSGHopOfChainMappedHere (self, cid, infra):
    """
    Returns an SGHop ID which is part of 'cid' chain and its path traverses 
    'infra'. Should be used when this infra is only used as forwarding infra, 
    but not as for hosting VNF for 'cid' (if not used like this, returns a random
    SGHop of the many, meeting the input criteria).
    """
    for c in self.chains:
      if cid == c['id']:
        for vnf1, vnf2, lid in zip(c['chain'][:-1], c['chain'][1:], 
                                   c['link_ids']):
          if infra in self.link_mapping[vnf1][vnf2][lid]['mapped_to']:
            return lid

  def genPathOfChains (self, nffg):
    """
    Returns a generator of the mapped stucture starting from the beginning of 
    chains and finding which Infra nodes are used during the mapping. Generates
    (chain_id, infra_id) tuples, and iterates on all chains. 
    Returns also SAPs on the path!
    """
    for c in self.chains:
      prev_infra_of_path = None
      for vnf1, vnf2, lid in zip(c['chain'][:-1], c['chain'][1:], 
                                 c['link_ids']):
        # iterate on 'mapped_to' attribute of vnf1,vnf2,lid link of 
        # link_mapping structure
        for forwarding_infra in \
            self.link_mapping[vnf1][vnf2][lid]['mapped_to']:
          if forwarding_infra is None or \
             forwarding_infra != prev_infra_of_path:
            prev_infra_of_path = forwarding_infra
            yield c['id'], forwarding_infra
      # VNF2 is handled by the iteration on link mapping structure (because 
      # 'mapped_to' contains the hosting infra of vnf1 and vnf2 as well)

  def getNextOutputChainId (self):
    self.max_input_chainid += 1
    return self.max_input_chainid

  def isAnyVNFInChain (self, cid, subgraph):
    """
    Checks whether any VNF of subgraph is a part of the given cid.
    """
    for vnf in subgraph.nodes_iter():
      for c in self.chains:
        if cid == c['id'] and vnf in c['chain']:
          return True
    return False

  def getChainPiecesOfReqSubgraph (self, cid, subgraph):
    """
    Iterates on all the "inbound" SGHops of this subgraph (these are not part 
    of the subgraph, they were the bordering edges in the request graph) and 
    finds the parts of the given chain (cid) which has any part mapped here. 
    We don't need the BiSBiS directly but all the VNF-s of subgraph should be 
    mapped to the same BiSBiS.
    """
    # A structure for storing SGHop
    # store list, there can be multiple disjoint chain parts mapped
    # here (if an internal VNF is mapped elsewhere)
    chain_pieces = []
    for i,j,k,d in self.colored_req.edges_iter(data=True, keys=True):
      if i not in subgraph.nodes_iter() and j in subgraph.nodes_iter():
        # i,j,k is an inbound SGHop from the (implicitly) given BiSBiS
        if cid in d['color']:
          for c in self.chains:
            if cid == c['id']:
              found_beginnig = False
              # i is not mapped to this Infra, but to the previous Infra.
              chain_piece = [i,j]
              link_ids_piece = [k]
              # find which part of the chain is mapped here
              for vnf1, vnf2, lid in zip(c['chain'][:-1], c['chain'][1:], 
                                         c['link_ids']):
                if not subgraph.has_edge(vnf1, vnf2, key=lid) and \
                   not found_beginnig:
                  continue
                elif not found_beginnig:
                  found_beginnig = True
                  if vnf1 != j:
                    raise uet.InternalAlgorithmException("Problem in chain "
                      "piece finding procedure for E2E requirement division.")
                if found_beginnig:
                  if subgraph.has_edge(vnf1, vnf2, key=lid):
                    chain_piece.append(vnf2)
                    link_ids_piece.append(lid)
                    continue
                  else:
                    break
              # vnf2 is mapped to the next Infra
              # the subgraph CAN'T have SAP-s, so vnf2 can be a SAP if 
              # this infra is the last to host a VNF for this chain
              chain_piece.append(vnf2)
              link_ids_piece.append(lid)
              chain_pieces.append((chain_piece, link_ids_piece))
              break
    return chain_pieces 

  def getRemainingE2ELatency (self, chain_id):
    """
    Returns the remaining latency of a given E2E chain.
    """
    return self.chain_subchain.node[chain_id]['avail_latency']
