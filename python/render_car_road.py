#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from overlay import overlay
from alpha_blend import alpha_blend
from lxml import etree as ET
from object_insertion import compose_and_blend
from map_mtl import map_mtl
import time


def generate_xml(xml_file, cam_to_world_matrix, cars_list, docker_mount, bsdf_list=None, render_ground=True, render_cars=True, is_hdr=False):
    
    tree = ET.parse('../assets/car_road_template.xml')
    root = tree.getroot()

    sensor_matrix = root.find('sensor').find('transform').find('matrix')
    sensor_matrix.set('value', cam_to_world_matrix) 

    if is_hdr:
        film = root.find('film')
        film.set('type', 'hdrfilm')

    for car in cars_list:   
        if render_cars:
            car_string = '''<shape type="obj">
                <string name="filename" value="{}"/>
                <transform name="toWorld">
                    <scale value="{}"/>

                    <rotate x="0" y="1" z="0" angle="{}" />
                    <translate x="{}" y="{}" z="{}" />
                </transform>
                
            </shape>
            '''.format(car['obj'], car['scale'], car['y_rotate'], car['x'], car['y'], car['z'])

            car_element = ET.fromstring(car_string)

            if bsdf_list is None:
                new_bsdf_list = map_mtl(car['obj'], docker_mount, ignore_textures=car['ignore_textures'])
            else:
                new_bsdf_list = bsdf_list
            
            for bsdf_str in new_bsdf_list:
                if bsdf_str is not None:
                    bsdf = ET.fromstring(bsdf_str)
                    car_element.append(bsdf)

            root.append(car_element)

        if render_ground:
            ground_string = '''<shape type="obj">
            <string name="filename" value="assets/ground.obj" />
            <transform name="toWorld">
                <scale value="0.05" />
                <rotate x="0" y="1" z="0" angle="{}" />
                <translate x="{}" y="{}" z="{}" />
            </transform>

            <bsdf type="roughdiffuse">
                <spectrum name="reflectance" value="0.1" />
                <float name="alpha" value="0.7" />
            </bsdf>

            </shape>'''.format(car['y_rotate'], car['x'], 0, car['z'])

            ground = ET.fromstring(ground_string)
            root.append(ground)


    tree.write(xml_file, encoding='utf-8', xml_declaration=True)
        

def calculate_car_pos(m, b, x_pos):
    """
    Given line z = m * x_pos + b, 
        where m = slope, b = displacement,
    Return z_pos

    """
    z_pos = m * x_pos + b

    return z_pos
   

MITSUBA_ARGS = {'turbidity':3, 'latitude':40.44694, 'longitude':-79.94902, 
    'timezone':-4, 'year':2021, 'month':5, 'day':1, 'hour':14, 'minute':43, 
    'sunScale':2, 'skyScale':2, 
    'fov':90, 'sampleCount':16, 'width':1000, 'height':750}


def render_car_road(output_dir, xml_name, cam_to_world_matrix, cars_list, 
        bg_img_path, rendered_img_name, composite_img_name, compose_mode, is_hdr_output, **kwargs):
    """
    See MITSUBA_ARGS dict initialization above for optional kwargs
    """

    # For each car in cars_list, calculate the correct z position,
    #   given the desired x position and line equation
    for i in range(len(cars_list)):
        cars_list[i]['z'] = calculate_car_pos(cars_list[i]['line_slope'], 
            cars_list[i]['line_displacement'], cars_list[i]['x'])
    
    # Im_all
    xml_path = output_dir + xml_name + ".xml"
    generate_xml(xml_path, cam_to_world_matrix, cars_list, output_dir, render_cars=True, render_ground=True, is_hdr=is_hdr_output)

    if compose_mode == "quotient":
        # Im_pl
        xml_path_pl = output_dir + xml_name + "_pl.xml"
        generate_xml(xml_path_pl, cam_to_world_matrix, cars_list, output_dir, render_cars=False, render_ground=True, is_hdr=is_hdr_output)

        # Im_obj
        xml_path_obj = output_dir + xml_name + "_obj.xml"
        generate_xml(xml_path_obj, cam_to_world_matrix, cars_list, output_dir, render_cars=True, render_ground=False, is_hdr=is_hdr_output)

    # handle kwargs
    for key in kwargs:
        MITSUBA_ARGS[key] = kwargs[key]

    cli_args = " "
    for key in MITSUBA_ARGS:
        cli_args += " -D {}={} ".format(key, MITSUBA_ARGS[key])

    if is_hdr_output:
        img_ext = ".exr"
    else:
        img_ext = ".png"
        
    pl_img = xml_name + "_pl" + img_ext
    obj_img = xml_name + "_obj" + img_ext

    with open('docker_script.sh', 'w') as outfn:
        outfn.write('cd /hosthome \n')
        # generate mitsuba command
        mts_cmd = "mitsuba" + cli_args + " -o " + rendered_img_name + " " + xml_name + ".xml \n"
        outfn.write(mts_cmd)

        if compose_mode == "quotient":
            mts_cmd = "mitsuba" + cli_args + " -o " + pl_img + " " + xml_name + "_pl.xml \n"
            outfn.write(mts_cmd)
            mts_cmd = "mitsuba" + cli_args + " -o " + obj_img + " " + xml_name + "_obj.xml \n"
            outfn.write(mts_cmd)

    docker_cmd = '''sudo docker run -v {}:/hosthome/ -it feb79bb374a0 /bin/bash -c \' bash /hosthome/python/docker_script.sh\''''.format(output_dir)
    startRenderTime = time.time()
    os.system(docker_cmd)
    print('Total rendering time: {}'.format(time.time() - startRenderTime))

    rendered_img_path = output_dir + rendered_img_name
    composite_img_path = output_dir + composite_img_name

    # compose render onto bg_img_path
    if compose_mode == "alpha":
        alpha_blend(bg_img_path, rendered_img_path, composite_img_path)
        print('Alpha blending for {} complete'.format(composite_img_path))
    elif compose_mode == "overlay":
        overlay(bg_img_path, rendered_img_path, composite_img_path)
        print('Overlay for {} complete'.format(composite_img_path))
    elif compose_mode == "quotient":
        compose_and_blend(bg_img_path, rendered_img_path, composite_img_path, 
            output_dir + pl_img, output_dir + obj_img)
        print('Overlay for {} complete'.format(composite_img_path))
   

if __name__ == '__main__':
    ######### Required arguments. Modify as desired: #############

    # This will be the docker volume mount:
    output_dir = "/home/gdsu/scenes/city_test/" 

    xml_name = "suv-test"
    cam_to_world_matrix = '-6.32009074e-01 3.81421015e-01  6.74598057e-01 -1.95597297e+01 '\
        '5.25615099e-03 8.72582680e-01 -4.88438164e-01  6.43714192e+00 '\
        '-7.74943161e-01  -3.05151563e-01 -5.53484978e-01  4.94516235e+00 '\
        '0 0 0 0.1'

    # car z position will be calculated later according to line equation
    # TODO: Note: obj path is weird...
    cars_list = [
        {"obj": "assets/cherokee-jeep/Jeep_Cherokee-TRI.obj", 
        "x": -17, "y": 0, "z": None, "scale": 1, "y_rotate": 315, 
        "line_slope":0.87, "line_displacement":3, "ignore_textures":False}, 
        {"obj": "assets/Nissan/Nissan-Rogue-2014/rogue-TRI.obj", 
        "x": -5, "y": 0, "z": None, "scale": 1, "y_rotate": 315, 
        "line_slope":0.87, "line_displacement":3, "ignore_textures":False},
        {"obj": "assets/toyota-land-cruiser/uploads_files_3120740_Toyota+Land+Cruiser+VXR-TRI.obj", 
        "x": 0, "y": 0, "z": None, "scale": 1, "y_rotate": 315, 
        "line_slope":0.87, "line_displacement":3, "ignore_textures":False},
        # {"obj": "assets/dmi-models/ford-gt/Ford_GT_2017-TRI.obj", 
        # "x": -8, "y": 0, "z": None, "scale": 1, "y_rotate": 225, 
        # "line_slope":0.95, "line_displacement":-3, "ignore_textures":False},
        # {"obj": "assets/dmi-models/mercedes/Mercedes_Sprinter_FedEx-TRI.obj", 
        # "x": -11, "y": 0, "z": None, "scale": 1, "y_rotate": 225, 
        # "line_slope":0.87, "line_displacement":-3, "ignore_textures":True},
        # {"obj": "assets/dmi-models/Mustang_GT/3D_Files/OBJ/mustang_GT-TRI.obj", 
        # "x": -15, "y": 0, "z": None, "scale": 1, "y_rotate": 225, 
        # "line_slope":-0.95, "line_displacement":-16.19, "ignore_textures":True},
        # {"obj": "assets/dmi-models/nypd/Dodge_Charger_Police_NYPD-TRI.obj", 
        # "x": -2, "y": 0, "z": None, "scale": 1, "y_rotate": 225, 
        # "line_slope":-0.95, "line_displacement":-5, "ignore_textures":False},
        # {"obj": "assets/dmi-models/toyota-camry/Toyota_Camry-TRI.obj", 
        # "x": -15, "y": 0, "z": None, "scale": 1, "y_rotate": 225, 
        # "line_slope":-0.95, "line_displacement":-14, "ignore_textures":True},
        ]


    bg_img_path = "../assets/cam2_week1_right_turn_2021-05-01T14-42-00.655968.jpg"
    compose_mode = "quotient" # "alpha", "overlay", or "quotient"


    rendered_img_name = xml_name + ".png"
    composite_img_name = xml_name + "_" + compose_mode + "_composite.png"
    is_hdr_output = False # if False, output ldr
    

    render_car_road(output_dir, xml_name, cam_to_world_matrix, cars_list, 
        bg_img_path, rendered_img_name, composite_img_name, compose_mode, is_hdr_output,
        width=1000, height=750, fov=90, sampleCount=32,
        # turbidity=3, latitude=40.5247051, longitude=-79.962172,
        # year=2022, month=3, day=16, hour=16, minute=30
        )
    