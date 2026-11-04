import pymeshlab

try:
    ms = pymeshlab.MeshSet()
    # Create a dummy mesh (cube)
    ms.create_cube()
    # We need two meshes for this filter (source and target), so create another one
    ms.create_cube()
    
    params = ms.filter_parameter_values('transfer_attributes_to_texture_per_vertex')
    print("Filter Parameters (Dictionary):")
    for key, value in params.items():
        print(f"{key}: {value}")
        
except Exception as e:
    print(f"Error: {e}")
