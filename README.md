# Ryu Controller

Controlador SDN desarrollado en Python con **Ryu** y **Mininet** para crear, visualizar, gestionar y probar topologías de red mediante una API REST.

El proyecto permite levantar topologías en Mininet, conectar switches OpenFlow a un controlador Ryu, consultar el estado de la red, aplicar cambios dinámicos sobre enlaces y puertos, ejecutar pruebas de tráfico y gestionar escenarios definidos en JSON.

## Características

* Controlador SDN basado en Ryu y OpenFlow 1.3.
* Integración con Mininet mediante un runner genérico.
* API REST para consultar y modificar el estado de la red.
* Soporte para topologías Python y escenarios JSON.
* Descubrimiento de switches, enlaces y hosts.
* Monitorización de puertos, flujos y métricas de salud.
* Gestión de tráfico con pruebas `ping`, `pingall` e `iperf`.
* Bloqueo y desbloqueo de tráfico por dirección IP.
* Soporte para STP y consulta del estado de convergencia.
* API auxiliar de Mininet para aplicar cambios en caliente.

## Estructura del proyecto

```text
ryu-controller/
├── mininet_live_api/        # API auxiliar para controlar Mininet en ejecución
├── scenarios/               # Escenarios JSON para importar o modificar topologías
├── sdn_api/                 # Controlador Ryu, servicios y rutas REST
├── topologies/              # Topologías Mininet en Python
├── mininet_runner_api.py    # Runner genérico para levantar Mininet con API
└── .gitignore
```

## Ramas del repositorio

| Rama                  | Descripción                                                                                                                                           |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main`                | Rama principal con la versión más completa e integrada del proyecto. Incluye API de Mininet, escenarios, servicios SDN, topologías y runner genérico. |
| `developer`           | Rama de desarrollo con trabajo intermedio y escenarios adicionales.                                                                                   |
| `create_net_elements` | Rama orientada a la creación y modificación dinámica de elementos de red.                                                                             |
| `api_with_stp`        | Rama centrada en la integración inicial de API REST con STP.                                                                                          |

Para cambiar de rama:

```bash
git checkout nombre-de-la-rama
```

Ejemplo:

```bash
git checkout developer
```

## Requisitos

Sistema recomendado:

* Linux / Ubuntu
* Python 3
* Mininet
* Open vSwitch
* Ryu
* `curl` para probar la API
* `iperf` o `iperf3` para pruebas de rendimiento

Instalación básica:

```bash
sudo apt update
sudo apt install -y python3 python3-pip mininet openvswitch-switch curl iperf3
pip3 install ryu webob
```

> Nota: el repositorio no incluye `requirements.txt`, por lo que las dependencias deben instalarse manualmente.

## Instalación

Clona el repositorio:

```bash
git clone https://github.com/Viictoor29/ryu-controller.git
cd ryu-controller
```

Usa la rama principal:

```bash
git checkout main
```

Limpia Mininet antes de empezar:

```bash
sudo mn -c
```

## Configuración de la API

La API usa la cabecera `X-API-Key`. Para evitar depender del valor por defecto del código, define tu propia clave:

```bash
export NETWORK_API_KEY="cambia-esta-clave"
```

Todas las peticiones protegidas deben incluir:

```bash
-H "X-API-Key: $NETWORK_API_KEY"
```

## Ejecución

Abre tres terminales.

### 1. Iniciar el controlador Ryu

Desde la raíz del proyecto:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

Por defecto, la API REST del controlador queda disponible en:

```text
http://127.0.0.1:8080
```

### 2. Iniciar Mininet con una topología

Ejemplo con la topología simple:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.simple_topo \
  --topo SimpleTopo \
  --controller-ip 127.0.0.1 \
  --controller-port 6653 \
  --api-port 8081 \
  --ryu-api-url http://127.0.0.1:8080
```

Ejemplo con la topología de tres switches:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.3s_topo \
  --topo s3Topo \
  --controller-ip 127.0.0.1 \
  --controller-port 6653 \
  --api-port 8081 \
  --ryu-api-url http://127.0.0.1:8080
```

El runner deja abierta la CLI de Mininet. Para salir:

```bash
exit
```

Después de salir, limpia el entorno:

```bash
sudo mn -c
```

### 3. Probar la API

Consultar la topología:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/topology
```

Consultar el estado del controlador:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/controller/status
```

Consultar métricas de salud:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/health
```

Consultar estado STP:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/stp/status
```

Ejecutar `pingall` desde la API:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"count": 1, "interval": 0.2, "timeout_per_ping": 5}' \
  http://127.0.0.1:8080/api/traffic/pingall
```

Bloquear tráfico de una IP:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"ip": "10.0.0.1"}' \
  http://127.0.0.1:8080/api/traffic/block-ip
```

Desbloquear tráfico de una IP:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"ip": "10.0.0.1"}' \
  http://127.0.0.1:8080/api/traffic/unblock-ip
```

Consultar IPs bloqueadas:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/traffic/blocked-ips
```

## Escenarios JSON

La carpeta `scenarios/` contiene escenarios que pueden utilizarse para probar cambios en la topología, estados degradados o configuraciones con STP.

Ejemplo de importación de topología:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/import
```

Validar una topología antes de importarla:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/validate
```

Exportar la topología actual:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  "http://127.0.0.1:8080/api/topology/export?name=mi_topologia"
```

## Topologías incluidas

### `SimpleTopo`

Archivo:

```text
topologies/simple_topo.py
```

Topología simple con dos switches y dos hosts:

* Switches: `s1`, `s5`
* Hosts: `h169`, `h69`
* Red: `10.0.0.0/24`

Ejecución:

```bash
sudo python3 mininet_runner_api.py --module topologies.simple_topo --topo SimpleTopo
```

### `s3Topo`

Archivo:

```text
topologies/3s_topo.py
```

Topología con tres switches y tres hosts:

* Switches: `s1`, `s5`, `s3`
* Hosts: `h169`, `h69`, `h170`
* Red: `10.0.0.0/24`

Ejecución:

```bash
sudo python3 mininet_runner_api.py --module topologies.3s_topo --topo s3Topo
```

## Endpoints principales

| Método | Endpoint                        | Descripción                                 |
| ------ | ------------------------------- | ------------------------------------------- |
| `GET`  | `/api/topology`                 | Devuelve la topología descubierta.          |
| `GET`  | `/api/topology/export`          | Exporta la topología actual.                |
| `POST` | `/api/topology/validate`        | Valida un escenario o topología JSON.       |
| `POST` | `/api/topology/import`          | Importa una topología desde JSON.           |
| `POST` | `/api/controller/runtime/reset` | Reinicia el estado interno del controlador. |
| `GET`  | `/api/controller/status`        | Devuelve el estado del controlador.         |
| `GET`  | `/api/health`                   | Devuelve métricas de salud.                 |
| `GET`  | `/api/health/summary`           | Devuelve resumen de salud.                  |
| `GET`  | `/api/switch/{dpid}/ports`      | Consulta puertos de un switch.              |
| `GET`  | `/api/switch/{dpid}/flows`      | Consulta flujos de un switch.               |
| `GET`  | `/api/stp/status`               | Consulta estado STP.                        |
| `POST` | `/api/traffic/ping`             | Ejecuta una prueba ping entre hosts.        |
| `POST` | `/api/traffic/pingall`          | Ejecuta ping entre todos los hosts.         |
| `POST` | `/api/traffic/iperf`            | Ejecuta una prueba de rendimiento.          |
| `POST` | `/api/traffic/block-ip`         | Bloquea tráfico de una IP.                  |
| `POST` | `/api/traffic/unblock-ip`       | Desbloquea tráfico de una IP.               |
| `POST` | `/api/traffic/unblock-all-ips`  | Desbloquea todas las IPs.                   |
| `GET`  | `/api/traffic/blocked-ips`      | Lista IPs bloqueadas.                       |
| `POST` | `/api/ports/loss`               | Aplica pérdida de paquetes a un puerto.     |
| `POST` | `/api/ports/bandwidth`          | Limita ancho de banda de un puerto.         |
| `POST` | `/api/ports/delay`              | Aplica retardo a un puerto.                 |
| `POST` | `/api/ports/tc/clear`           | Limpia configuración `tc` de un puerto.     |

## Flujo recomendado de trabajo

1. Iniciar Ryu con `--observe-links`.
2. Levantar Mininet con `mininet_runner_api.py`.
3. Consultar `/api/topology` para comprobar que la red se ha descubierto correctamente.
4. Ejecutar `/api/traffic/pingall` para validar conectividad.
5. Probar cambios de topología o escenarios JSON.
6. Revisar `/api/stp/status`, `/api/health` y `/api/switch/{dpid}/flows`.
7. Limpiar Mininet con `sudo mn -c` al terminar.

## Solución de problemas

### La API devuelve `No autorizado`

Comprueba que estás enviando la cabecera:

```bash
-H "X-API-Key: $NETWORK_API_KEY"
```

Y que la variable está definida en la terminal donde ejecutas Ryu:

```bash
echo $NETWORK_API_KEY
```

### Mininet no conecta con Ryu

Comprueba que Ryu está escuchando antes de arrancar Mininet y que el puerto coincide:

```bash
--controller-ip 127.0.0.1
--controller-port 6653
```

### No aparecen enlaces en la topología

Ejecuta Ryu con:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

Sin `--observe-links`, Ryu puede no descubrir los enlaces correctamente.

### Quedan interfaces antiguas de Mininet

Limpia el entorno:

```bash
sudo mn -c
```

## Desarrollo

Para añadir una nueva topología:

1. Crea un archivo en `topologies/`.
2. Define una clase que herede de `Topo`.
3. Añade switches, hosts y enlaces en el método `build`.
4. Ejecuta el runner indicando el módulo y la clase.

Ejemplo:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.mi_topologia \
  --topo MiTopologia
```

Para añadir nuevas rutas REST, modifica o amplía los servicios dentro de `sdn_api/` y registra la ruta correspondiente en `rest_routes.py`.

## Licencia

Este repositorio no especifica una licencia. Si el proyecto se va a compartir o reutilizar públicamente, se recomienda añadir un archivo `LICENSE`.
