from PyQt6.QtWidgets import QApplication
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtGui import QOpenGLShader, QOpenGLShaderProgram
import sys

app = QApplication(sys.argv)

class TestGL(QOpenGLWidget):
    def initializeGL(self):
        vertex_shader = """
        #version 330 core
        layout (location = 0) in vec3 position;
        void main() { gl_Position = vec4(position, 1.0); }
        """
        fragment_shader = """
        #version 330 core
        uniform int viz_mode;
        uniform int zebra_direction;
        uniform float zebra_scale;
        uniform float curvature_scale;
        in vec3 v_normal;
        in vec3 v_pos;
        uniform vec3 view_pos;
        
        out vec4 frag_color;
        
        vec3 get_heat_map_color(float value) { return vec3(value); }

        void main() {
            vec3 final_rgb = vec3(1.0);
            if (viz_mode == 9) { // Zebra Map
                vec3 view_dir = normalize(view_pos - v_pos);
                vec3 norm = normalize(v_normal);
                vec3 ref_dir = reflect(-view_dir, norm);
                float coord = (zebra_direction == 0) ? ref_dir.y : ref_dir.x; 
                float pattern = fract(coord * zebra_scale * 10.0);
                float intensity = smoothstep(0.4, 0.6, pattern);
                final_rgb = vec3(intensity);
            } else if (viz_mode == 10) { // Curvature Map
                vec3 norm = normalize(v_normal);
                vec3 dx = dFdx(norm);
                vec3 dy = dFdy(norm);
                float curvature = length(dx) + length(dy);
                curvature = clamp(curvature * curvature_scale * 10.0, 0.0, 1.0);
                final_rgb = get_heat_map_color(curvature);
            }
            frag_color = vec4(final_rgb, 1.0);
        }
        """
        prog = QOpenGLShaderProgram()
        vs_ok = prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex_shader)
        print("VS:", vs_ok, prog.log())
        fs_ok = prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment_shader)
        print("FS:", fs_ok, prog.log())
        linked = prog.link()
        print("LINK:", linked, prog.log())

w = TestGL()
w.show()
app.processEvents()
