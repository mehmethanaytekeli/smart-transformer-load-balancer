from flask import Flask, render_template, request, jsonify
import threading
import time
import board
import busio
from adafruit_ina219 import INA219
import lgpio
import atexit

# === Röle Pinleri ===
RELAY1_PIN = 17
RELAY2_PIN = 27

# === Başlangıç Eşik Değeri (mA cinsinden) ===
current_threshold = 2000  # 2A başlangıç

# === lgpio Kurulumu ===
h = lgpio.gpiochip_open(0)

def cleanup_gpio():
    try:
        lgpio.gpio_write(h, RELAY1_PIN, 1)
        lgpio.gpio_write(h, RELAY2_PIN, 1)
        lgpio.gpio_free(h, RELAY1_PIN)
        lgpio.gpio_free(h, RELAY2_PIN)
        lgpio.gpiochip_close(h)
    except Exception as e:
        print("GPIO temizleme hatası:", e)

atexit.register(cleanup_gpio)

try:
    lgpio.gpio_claim_output(h, RELAY1_PIN)
    lgpio.gpio_claim_output(h, RELAY2_PIN)
    lgpio.gpio_write(h, RELAY1_PIN, 0)  # Trafo 1 açık
    lgpio.gpio_write(h, RELAY2_PIN, 1)  # Trafo 2 kapalı
except Exception as e:
    print("GPIO başlatma hatası:", e)
    cleanup_gpio()
    exit(1)

# === INA219 Sensör Kurulumu ===
try:
    i2c_bus = busio.I2C(board.SCL, board.SDA)
    ina1 = INA219(i2c_bus, addr=0x40)
    ina2 = INA219(i2c_bus, addr=0x41)
except Exception as e:
    print("Sensör başlatma hatası:", e)
    cleanup_gpio()
    exit(1)

# === Flask Uygulaması ===
app = Flask(__name__)

data = {
    "trafo1": {"voltage": 0, "current": 0, "power": 0},
    "trafo2": {"voltage": 0, "current": 0, "power": 0},
    "relay1": False,
    "relay2": True,
    "threshold": current_threshold,
    "history": []
}

relay2_enabled = False  # Başlangıçta kapalı

def sensor_loop():
    global data, current_threshold, relay2_enabled
    while True:
        try:
            # Trafo 1 ölçüm
            v1 = ina1.bus_voltage + 0.01
            i1 = abs(ina1.current)
            p1 = v1 * (i1 / 1000)

            # Trafo 2 ölçüm
            v2 = ina2.bus_voltage + 0.01
            i2 = abs(ina2.current)
            p2 = v2 * (i2 / 1000)

            total_current = i1 + i2

            # Röle kontrol (%5 histerezis)
            if not relay2_enabled and total_current > current_threshold:
                lgpio.gpio_write(h, RELAY2_PIN, 0)  # Aç
                relay2_enabled = True
            elif relay2_enabled and total_current < current_threshold * 0.95:
                lgpio.gpio_write(h, RELAY2_PIN, 1)  # Kapat
                relay2_enabled = False

            # Röle pinlerini oku
            relay1_state = lgpio.gpio_read(h, RELAY1_PIN)
            relay2_state = lgpio.gpio_read(h, RELAY2_PIN)

            # Verileri güncelle
            data["trafo1"] = {
                "voltage": round(v1, 2),
                "current": round(i1, 1),
                "power": round(p1, 2)
            }
            data["trafo2"] = {
                "voltage": round(v2, 2),
                "current": round(i2, 1),
                "power": round(p2, 2)
            }
            data["relay1"] = True if relay1_state == 0 else False
            data["relay2"] = True if relay2_state == 0 else False
            data["threshold"] = round(current_threshold, 1)

            if len(data["history"]) >= 60:
                data["history"].pop(0)
            data["history"].append({
                "t1": round(i1, 1),
                "t2": round(i2, 1)
            })

        except Exception as e:
            print("Sensör Hatası:", e)

        time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def get_data():
    return jsonify(data)

@app.route('/set_threshold', methods=['POST'])
def set_threshold():
    global current_threshold
    try:
        new_threshold = float(request.form['threshold'])
        if 100 <= new_threshold <= 5000:
            current_threshold = new_threshold
    except ValueError:
        pass
    return ('', 204)

sensor_thread = threading.Thread(target=sensor_loop, daemon=True)
sensor_thread.start()

if __name__ == "__main__":
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("Sunucu kapatılıyor...")
    finally:
        cleanup_gpio()
