from typing import ClassVar, Optional, Any, Union, Literal, Iterable, TypedDict
import math
#from glayout.flow.pdk.gf180_mapped import gf180
from glayout.flow.pdk.sky130_mapped import sky130_mapped_pdk as sky130
from glayout.flow.pdk.mappedpdk import MappedPDK
from glayout.flow.pdk.util.comp_utils import evaluate_bbox
from glayout.flow.pdk.util.port_utils import set_port_orientation, rename_ports_by_orientation, create_private_ports
from gdsfactory import Component
from gdsfactory.components import rectangle
from glayout.flow.primitives.fet import pmos
from glayout.flow.primitives.fet import nmos
from glayout.flow.routing.straight_route import straight_route
from glayout.flow.routing.c_route import c_route
from glayout.flow.routing.L_route import L_route
from glayout.flow.routing.smart_route import smart_route
from glayout.flow.placement.two_transistor_interdigitized import two_pfet_interdigitized, two_nfet_interdigitized, two_transistor_interdigitized
from glayout.flow.placement.common_centroid_ab_ba import common_centroid_ab_ba
from glayout.flow.pdk.util.comp_utils import prec_ref_center, movey, evaluate_bbox, align_comp_to_port
from glayout.flow.primitives.via_gen import via_stack

# My own cell library
from reconfig_inv import reconfig_inv
import comp_dc

#@cell
def short_channel_tg(
	pdk: MappedPDK,
	component_name: str,
	orientation_config:
	dict[str, Union[int, str]],
	pmos_width,
	pmos_length,
	nmos_width,
	nmos_length,
	add_pin: bool = True, # For LVS
	**kwargs
) -> Component:
	# To prepare all necessary cells to construct a transmission gate, i.e.
	# 1) PMOS
	# 2) NMOS
	pfet = pmos(pdk=pdk, gate_rmult=2, with_tie=False, with_substrate_tap=False, with_dummy=(True, False), width=pmos_width, length=pmos_length)
	nfet = nmos(pdk=pdk, gate_rmult=2, with_tie=False, with_dnwell=False, with_substrate_tap=False, with_dummy=(False, True), width=nmos_width, length=nmos_length)

	# Placement and adding ports
	top_level = Component(name=component_name)
	pfet_ref = prec_ref_center(pfet)
	nfet_ref = prec_ref_center(nfet)
	top_level.add(pfet_ref)
	top_level.add(nfet_ref)

	# Placement
	mos_spacing = pdk.util_max_metal_seperation()
	if orientation_config["degree"] != None:
		pfet_ref.rotate(orientation_config["degree"])
		nfet_ref.rotate(orientation_config["degree"])
	pfet_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing)

	# Routing
	# To simplify the routing for the parallel-gate transistors, the layout is realised as follow which is expected to be equivalent to a TG
	#     a) PMOS.source connected to NMOS.source
	#     b) PMOS.drain connected to NMOS.drain 
	top_level << straight_route(pdk, pfet_ref.ports["multiplier_0_source_E"], nfet_ref.ports["multiplier_0_drain_E"], glayer1="met2") # "in" of the TG
	top_level << straight_route(pdk, pfet_ref.ports["multiplier_0_drain_E"], nfet_ref.ports["multiplier_0_source_E"], glayer1="met2") # "out" of the TG

	# Add the ports aligned with the basic PMOS and NMOS
	top_level.add_ports(pfet_ref.get_ports_list(), prefix="pmos_")
	top_level.add_ports(nfet_ref.get_ports_list(), prefix="nmos_")

	if add_pin == True:
		# Add pins w/ labels for LVS
		top_level.unlock()
		pin_info = list() # list that contains all port and component information
		met1_pin=(pdk.get_glayer("met1")[0], 20)
		met1_label=(pdk.get_glayer("met1")[0], 5)
		port_size = (0.24, 0.24)
		# --- Port: A, i.e. input of the transmission gate
		A_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		A_pin.add_label(text="A", layer=met1_label)
		pin_info.append((A_pin, top_level.ports.get(f"nmos_drain_S"), None))
		# --- Port: Y, i.e. output of the transmission gate
		Y_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		Y_pin.add_label(text="Y", layer=met1_label)
		pin_info.append((Y_pin, top_level.ports.get(f"pmos_drain_S"), None))
		# --- Port: C, i.e. gate control to the NMOS
		C_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		C_pin.add_label(text="C", layer=met1_label)
		pin_info.append((C_pin, top_level.ports.get(f"nmos_gate_N"), None))
		# --- Port: CBAR, i.e. gate control to the PMOS
		CBAR_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		CBAR_pin.add_label(text="CBAR", layer=met1_label)
		pin_info.append((CBAR_pin, top_level.ports.get(f"pmos_gate_N"), None))

		# Move everythin to position
		for comp, prt, alignment in pin_info:
			alignment = ('c', 'b') if alignment is None else alignment
			comp_ref = align_comp_to_port(comp, prt, alignment=alignment)
			top_level.add(comp_ref)

	return top_level

#@cell
def long_channel_tg(
	pdk: MappedPDK,
	component_name: str,
	orientation_config:
	dict[str, Union[int, str]],
	pmos_width,
	pmos_length,
	nmos_width,
	nmos_length,
	add_pin: bool = True, # For LVS
	**kwargs
) -> Component:
	# To calculate the number of fingers for the underlying PMOS/NMOS layout
	finger_num = math.ceil(pmos_width / comp_dc.tg_channel_width_base)
	mos_width = comp_dc.tg_channel_width_base

	# To prepare all necessary cells to construct a transmission gate, i.e.
	# 1) PMOS
	# 2) NMOS
	pfet = pmos(pdk=pdk, multipliers=1, fingers=finger_num, interfinger_rmult=3, gate_rmult=1, with_tie=False, with_substrate_tap=False, with_dummy=(False, False), width=mos_width, length=pmos_length)
	nfet = nmos(pdk=pdk, multipliers=1, fingers=finger_num, interfinger_rmult=3, gate_rmult=1, with_tie=False, with_dnwell=False, with_substrate_tap=False, with_dummy=(False, False), width=mos_width, length=nmos_length)

	# Placement and adding ports
	top_level = Component(name=component_name)
	pfet_ref = prec_ref_center(pfet)
	nfet_ref = prec_ref_center(nfet)
	top_level.add(pfet_ref)
	top_level.add(nfet_ref)

	# Placement
	mos_spacing = pdk.util_max_metal_seperation()
	#if orientation_config["pmos_degree"] != None:
	#	pfet_ref.rotate(orientation_config["pmos_degree"])
	#if orientation_config["nmos_degree"] != None:
	#	nfet_ref.rotate(orientation_config["nmos_degree"])
	rename_ports_by_orientation(nfet_ref.mirror_y()) # To vertically flip the NMOS such that the its gate point toward the PMOS's gate 
	pfet_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing)


	pmos_drain_viaStack = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	pmos_drain_viaStack1 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	pmos_drain_viaStack2 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	pmos_drain_viaStack3 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	pmos_drain_viaStack4 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	pmos_drain_viaStack5 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")

	nmos_drain_viaStack = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	nmos_drain_viaStack1 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	nmos_drain_viaStack2 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	nmos_drain_viaStack3 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	nmos_drain_viaStack4 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")
	nmos_drain_viaStack5 = via_stack(pdk=pdk, glayer1="met2", glayer2="met3")

	pmos_drain_viaStack_ref = prec_ref_center(pmos_drain_viaStack)
	pmos_drain_viaStack1_ref = prec_ref_center(pmos_drain_viaStack1)
	pmos_drain_viaStack2_ref = prec_ref_center(pmos_drain_viaStack2)
	pmos_drain_viaStack3_ref = prec_ref_center(pmos_drain_viaStack3)
	pmos_drain_viaStack4_ref = prec_ref_center(pmos_drain_viaStack4)
	pmos_drain_viaStack5_ref = prec_ref_center(pmos_drain_viaStack5)
	nmos_drain_viaStack_ref = prec_ref_center(nmos_drain_viaStack)
	nmos_drain_viaStack1_ref = prec_ref_center(nmos_drain_viaStack1)
	nmos_drain_viaStack2_ref = prec_ref_center(nmos_drain_viaStack2)
	nmos_drain_viaStack3_ref = prec_ref_center(nmos_drain_viaStack3)
	nmos_drain_viaStack4_ref = prec_ref_center(nmos_drain_viaStack4)
	nmos_drain_viaStack5_ref = prec_ref_center(nmos_drain_viaStack5)
	top_level.add(pmos_drain_viaStack_ref)
	top_level.add(pmos_drain_viaStack1_ref)
	top_level.add(pmos_drain_viaStack2_ref)
	top_level.add(pmos_drain_viaStack3_ref)
	top_level.add(pmos_drain_viaStack4_ref)
	top_level.add(pmos_drain_viaStack5_ref)
	top_level.add(nmos_drain_viaStack_ref)
	top_level.add(nmos_drain_viaStack1_ref)
	top_level.add(nmos_drain_viaStack2_ref)
	top_level.add(nmos_drain_viaStack3_ref)
	top_level.add(nmos_drain_viaStack4_ref)
	top_level.add(nmos_drain_viaStack5_ref)

	pmos_drain_viaStack_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing)
	pmos_drain_viaStack1_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing)
	pmos_drain_viaStack2_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing)
	pmos_drain_viaStack3_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing - pdk.get_grule("met3")["min_separation"] - pdk.get_grule("met3")["min_width"])
	pmos_drain_viaStack4_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing - pdk.get_grule("met3")["min_separation"] - pdk.get_grule("met3")["min_width"])
	pmos_drain_viaStack5_ref.movey(evaluate_bbox(nfet)[1] + mos_spacing - pdk.get_grule("met3")["min_separation"] - pdk.get_grule("met3")["min_width"])
	nmos_drain_viaStack3_ref.movey(pdk.get_grule("met3")["min_separation"]+pdk.get_grule("met3")["min_width"])
	nmos_drain_viaStack4_ref.movey(pdk.get_grule("met3")["min_separation"]+pdk.get_grule("met3")["min_width"])
	nmos_drain_viaStack5_ref.movey(pdk.get_grule("met3")["min_separation"]+pdk.get_grule("met3")["min_width"])
	pmos_drain_viaStack1_ref.movex(pfet_ref.ports["source_W"].center[0]+0.15)
	pmos_drain_viaStack2_ref.movex(-pfet_ref.ports["source_W"].center[0]-0.15)
	pmos_drain_viaStack4_ref.movex(pfet_ref.ports["source_W"].center[0]+0.15)
	pmos_drain_viaStack5_ref.movex(-pfet_ref.ports["source_W"].center[0]-0.15)
	nmos_drain_viaStack1_ref.movex(pfet_ref.ports["source_W"].center[0]+0.15)
	nmos_drain_viaStack2_ref.movex(-pfet_ref.ports["source_W"].center[0]-0.15)
	nmos_drain_viaStack4_ref.movex(pfet_ref.ports["source_W"].center[0]+0.15)
	nmos_drain_viaStack5_ref.movex(-pfet_ref.ports["source_W"].center[0]-0.15)

	c = Component()
	c.add_polygon(
		[
			(nmos_drain_viaStack1_ref.xmin, nmos_drain_viaStack1_ref.ymin),#leftBottom_pos
			(nmos_drain_viaStack2_ref.xmax, nmos_drain_viaStack2_ref.ymin),#rightBottom_pos
			(pmos_drain_viaStack2_ref.xmax, pmos_drain_viaStack2_ref.ymax),#rightTop_pos
			(pmos_drain_viaStack1_ref.xmin, pmos_drain_viaStack1_ref.ymax) #leftTop_pos
		],
		layer=pdk.get_glayer("met3")
	)
	c_ref = top_level.add_ref(c)

	# Routing
	# To simplify the routing for the parallel-gate transistors, the layout is realised as follow which is expected to be equivalent to a TG
	#     a) PMOS.source connected to NMOS.source
	#     b) PMOS.drain connected to NMOS.drain
	top_level << c_route(pdk, pfet_ref.ports["drain_E"], nfet_ref.ports["drain_E"], cglayer="met3") # "out" of the TG

	#top_level << straight_route(pdk, pmos_drain_viaStack_ref.ports["top_met_S"], nmos_drain_viaStack_ref.ports["top_met_S"])#, glayer1="met3")
	#top_level << straight_route(pdk, pmos_drain_viaStack1_ref.ports["top_met_S"], nmos_drain_viaStack1_ref.ports["top_met_S"])
	#top_level << straight_route(pdk, pmos_drain_viaStack2_ref.ports["top_met_S"], nmos_drain_viaStack2_ref.ports["top_met_S"])

	# Add the ports aligned with the basic PMOS and NMOS
	top_level.add_ports(pfet_ref.get_ports_list(), prefix="pmos_")
	top_level.add_ports(nfet_ref.get_ports_list(), prefix="nmos_")

	if add_pin == True:
		# Add pins w/ labels for LVS
		top_level.unlock()
		pin_info = list() # list that contains all port and component information
		met1_pin=(pdk.get_glayer("met1")[0], 20)
		met1_label=(pdk.get_glayer("met1")[0], 5)
		port_size = (0.24, 0.24)
		# --- Port: A, i.e. input of the transmission gate
		A_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		A_pin.add_label(text="A", layer=met1_label)
		pin_info.append((A_pin, top_level.ports.get(f"nmos_source_S"), None))
		# --- Port: Y, i.e. output of the transmission gate
		Y_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		Y_pin.add_label(text="Y", layer=met1_label)
		pin_info.append((Y_pin, top_level.ports.get(f"nmos_drain_S"), None))
		# --- Port: C, i.e. gate control to the NMOS
		C_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		C_pin.add_label(text="C", layer=met1_label)
		pin_info.append((C_pin, top_level.ports.get(f"nmos_gate_N"), None))
		# --- Port: CBAR, i.e. gate control to the PMOS
		CBAR_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		CBAR_pin.add_label(text="CBAR", layer=met1_label)
		pin_info.append((CBAR_pin, top_level.ports.get(f"pmos_gate_N"), None))

		# Move everythin to position
		for comp, prt, alignment in pin_info:
			alignment = ('c', 'b') if alignment is None else alignment
			comp_ref = align_comp_to_port(comp, prt, alignment=alignment)
			top_level.add(comp_ref)

	return top_level

#@cell
def tg_with_ctrl(
	pdk: MappedPDK,
	component_name: str,
	pmos_width,
	pmos_length,
	nmos_width,
	nmos_length,
	add_pin: bool = True, # For LVS
	**kwargs
) -> Component:
	# To prepare all necessary cells to construct a transmission gate, i.e.
	# 1) transmission gate
	# 2) Inverter
	tg = tg_cell(
		pdk=pdk,
		component_name="tg",
		orientation_config={"degree": 270},
		pmos_width=pmos_width,
		pmos_length=pmos_length,
		nmos_width=nmos_width,
		nmos_length=nmos_length,
		add_pin=False
	)
	inv = reconfig_inv(
		pdk=pdk,
		component_name="gate_ctrl_inv",
		pmos_width=pmos_width,
		pmos_length=pmos_length,
		nmos_width=nmos_width,
		nmos_length=nmos_length,
		orientation="horizontal",
		add_pin=False
	)

	# Instantiation of the essential cells
	top_level = Component(name=component_name)
	tg_ref = prec_ref_center(tg)
	inv_ref = prec_ref_center(inv)
	top_level.add(tg_ref)
	top_level.add(inv_ref)

	# Placement
	mos_spacing = pdk.util_max_metal_seperation()
	nwell_min_spacing = pdk.get_grule("nwell")["min_separation"]
	inv_cell_width = inv_ref.xsize # or = evaluate_bbox(inv)[0]
	tg_ref.movex(inv_cell_width + nwell_min_spacing)

	# Routing
	#    1) PMOS of the TG is switched on/off by the inverter's output
	#    2) NMOS of the TG is switched on/off by an external control signal connected to inverter's input port as well
	top_level << smart_route(pdk, inv_ref.ports["pmos_multiplier_0_drain_E"], tg_ref.ports["pmos_multiplier_0_gate_W"])
	top_level << straight_route(pdk, inv_ref.ports["nmos_multiplier_0_gate_S"], tg_ref.ports["nmos_multiplier_0_gate_S"], glayer1="met3")

	# Adding the ports
	top_level.add_ports(tg_ref.get_ports_list(), prefix="tg_")
	top_level.add_ports(inv_ref.get_ports_list(), prefix="inv_")
	
	if add_pin == True:
		# Add pins w/ labels for LVS
		top_level.unlock()
		pin_info = list() # list that contains all port and component information
		met1_pin=(pdk.get_glayer("met1")[0], 20)
		met1_label=(pdk.get_glayer("met1")[0], 5)
		port_size = (0.24, 0.24)
		# --- Port: A, i.e. input of the transmission gate
		A_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		A_pin.add_label(text="A", layer=met1_label)
		pin_info.append((A_pin, top_level.ports.get(f"tg_nmos_drain_S"), None))
		# --- Port: Y, i.e. output of the transmission gate
		Y_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		Y_pin.add_label(text="Y", layer=met1_label)
		pin_info.append((Y_pin, top_level.ports.get(f"tg_pmos_drain_S"), None))
		# --- Port: C, i.e. gate control to the NMOS
		C_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		C_pin.add_label(text="C", layer=met1_label)
		pin_info.append((C_pin, top_level.ports.get(f"inv_nmos_gate_N"), None))
		# --- Port: VDD
		VDD_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		VDD_pin.add_label(text="VDD", layer=met1_label)
		pin_info.append((VDD_pin, top_level.ports.get(f"inv_pmos_drain_E"), None))
		# --- Port: VSS
		VSS_pin=rectangle(layer=met1_pin, size=port_size, centered=True).copy()
		VSS_pin.add_label(text="VSS", layer=met1_label)
		pin_info.append((VSS_pin, top_level.ports.get(f"inv_nmos_source_W"), ('r', 't')))

		# Move everythin to position
		for comp, prt, alignment in pin_info:
			alignment = ('c', 'b') if alignment is None else alignment
			comp_ref = align_comp_to_port(comp, prt, alignment=alignment)
			top_level.add(comp_ref)	

	return top_level

#@cell
def reconfig_tg(
	pdk: MappedPDK,
	component_name,
	pmos_width,
	pmos_length,
	nmos_width,
	nmos_length,
	add_pin: bool = True, # For LVS
	**kwargs
) -> Component:
	if pmos_width != nmos_width:
		raise ValueError("PCell constraint: the widths of PMOS and NMOS must be identical")
	elif pmos_width >= comp_dc.tg_channel_width_base: # Long-channel PMOS and NMOS
		tg = long_channel_tg(
			pdk=pdk,
			component_name=component_name,
			orientation_config={"nmos_degree": 180, "pmos_degree": 0},
			pmos_width=pmos_width,
			pmos_length=pmos_length,
			nmos_width=nmos_width,
			nmos_length=nmos_length,
			add_pin=True
		)
	else: # Short-channel PMOS and NMOS
		tg = short_channel_tg(
			pdk=pdk,
			component_name=component_name,
			orientation_config={"degree": 270},
			pmos_width=pmos_width,
			pmos_length=pmos_length,
			nmos_width=nmos_width,
			nmos_length=nmos_length,
			add_pin=True
		)

	return tg