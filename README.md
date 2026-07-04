# Ryu Controller

Controlador SDN desarrollado en Python con **Ryu** y **Mininet** para crear, visualizar, gestionar y probar topologías de red mediante APIs REST.

El proyecto permite levantar topologías en Mininet, conectar switches OpenFlow a un controlador Ryu, consultar el estado de la red, aplicar cambios dinámicos sobre enlaces y puertos, ejecutar pruebas de tráfico, gestionar escenarios definidos en JSON y controlar la red emulada en caliente.

## Características

* Controlador SDN basado en Ryu y OpenFlow 1.3.
* Integración con Mininet mediante un runner genérico.
* API REST del controlador Ryu para consultar y modificar el estado lógico de la red.
* API REST auxiliar de Mininet para crear, borrar y modificar elementos de la red emulada.
* Soporte para topologías Python y escenarios JSON.
* Descubrimiento de switches, enlaces y hosts.
* Monitorización de puertos, flujos y métricas de salud.
* Gestión de tráfico con pruebas `ping`, `pingall` e `iperf`.
* Bloqueo y desbloqueo de tráfico por dirección IP.
* Soporte para STP y consulta del estado de convergencia.
* Aplicación de pérdida, retardo y ancho de banda sobre enlaces o puertos.
* Creación dinámica de hosts, switches y enlaces desde la API de Mininet.
* Exportación e importación de topologías.

## Arquitectura general

El proyecto trabaja con dos APIs REST diferentes:

| API         | Puerto por defecto | Descripción                                                                                                                        |
| ----------- | -----------------: | ---------------------------------------------------------------------------------------------------------------------------------- |
| API Ryu     |             `8080` | API del controlador SDN. Gestiona topología descubierta, flujos, STP, tráfico, salud de red, enlaces, puertos y políticas.         |
| API Mininet |             `8081` | API auxiliar de la red emulada. Permite crear y eliminar hosts, switches, enlaces y aplicar topologías directamente sobre Mininet. |

Flujo básico:

1. Se inicia el controlador Ryu.
2. Se inicia Mininet con una topología.
3. Los switches de Mininet se conectan al controlador Ryu por OpenFlow.
4. Ryu expone su API REST en `8080`.
5. El runner de Mininet expone la API auxiliar de Mininet en `8081`.
6. Desde un cliente externo, como `curl`, Postman o Gestordered, se pueden consumir ambas APIs.

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

## Configuración de la clave de API

Tanto la API Ryu como la API Mininet usan la cabecera `X-API-Key`.

Para definir la clave de API:

```bash
export NETWORK_API_KEY="cambia-esta-clave"
```

Todas las peticiones protegidas deben incluir:

```bash
-H "X-API-Key: $NETWORK_API_KEY"
```

Si no se define la variable `NETWORK_API_KEY`, el proyecto puede usar una clave por defecto definida en el código. Aun así, se recomienda definir una clave propia para evitar depender de valores fijos.

## Ejecución

Abre tres terminales.

## 1. Iniciar el controlador Ryu

Desde la raíz del proyecto:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

Por defecto, la API REST del controlador Ryu queda disponible en:

```text
http://127.0.0.1:8080
```

El parámetro `--observe-links` es importante para que Ryu pueda descubrir enlaces entre switches.

## 2. Iniciar Mininet con una topología

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

La API auxiliar de Mininet queda disponible en:

```text
http://127.0.0.1:8081
```

El runner deja abierta la CLI de Mininet. Para salir:

```bash
exit
```

Después de salir, limpia el entorno:

```bash
sudo mn -c
```

## 3. Probar las APIs

Consultar la topología desde Ryu:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/topology
```

Consultar el estado de Mininet:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/status
```

## API Ryu

La **API Ryu** se ejecuta por defecto en:

```text
http://127.0.0.1:8080
```

Esta API representa la parte del controlador SDN. Sirve para consultar la topología descubierta por Ryu, revisar el estado de switches y flujos, gestionar STP, lanzar pruebas de tráfico, bloquear IPs y aplicar cambios lógicos sobre enlaces y puertos.

### Endpoints de topología

| Método | Endpoint                 | Descripción                                               |
| ------ | ------------------------ | --------------------------------------------------------- |
| `GET`  | `/api/topology`          | Devuelve la topología descubierta por el controlador.     |
| `GET`  | `/api/topology/export`   | Exporta la topología actual.                              |
| `POST` | `/api/topology/validate` | Valida un escenario o topología JSON antes de importarlo. |
| `POST` | `/api/topology/import`   | Importa una topología desde JSON.                         |

Ejemplo:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/topology
```

Exportar la topología actual:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  "http://127.0.0.1:8080/api/topology/export?name=mi_topologia"
```

Validar una topología:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/validate
```

Importar una topología:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/import
```

### Endpoints del controlador y salud

| Método | Endpoint                        | Descripción                                 |
| ------ | ------------------------------- | ------------------------------------------- |
| `POST` | `/api/controller/runtime/reset` | Reinicia el estado interno del controlador. |
| `GET`  | `/api/controller/status`        | Devuelve el estado del controlador.         |
| `GET`  | `/api/health`                   | Devuelve métricas de salud de la red.       |
| `GET`  | `/api/health/summary`           | Devuelve un resumen del estado de salud.    |

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

Reiniciar estado interno del controlador:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"preserve_blocked_ips": false, "flush_flows": true, "clear_deleted_hosts": false}' \
  http://127.0.0.1:8080/api/controller/runtime/reset
```

### Endpoints de switches

| Método | Endpoint                   | Descripción                                  |
| ------ | -------------------------- | -------------------------------------------- |
| `GET`  | `/api/switch/{dpid}/ports` | Consulta los puertos de un switch.           |
| `GET`  | `/api/switch/{dpid}/flows` | Consulta los flujos instalados en un switch. |

Ejemplo:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/switch/0000000000000001/ports
```

Consultar flujos:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/switch/0000000000000001/flows
```

### Endpoints de STP

| Método | Endpoint          | Descripción                |
| ------ | ----------------- | -------------------------- |
| `GET`  | `/api/stp/status` | Consulta el estado de STP. |

Ejemplo:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/stp/status
```

### Endpoints de tráfico

| Método | Endpoint                       | Descripción                                  |
| ------ | ------------------------------ | -------------------------------------------- |
| `POST` | `/api/traffic/ping`            | Ejecuta una prueba ping entre dos hosts.     |
| `POST` | `/api/traffic/pingall`         | Ejecuta ping entre todos los hosts.          |
| `POST` | `/api/traffic/iperf`           | Ejecuta una prueba de rendimiento con iperf. |
| `POST` | `/api/traffic/block-ip`        | Bloquea el tráfico de una IP.                |
| `POST` | `/api/traffic/unblock-ip`      | Desbloquea el tráfico de una IP.             |
| `POST` | `/api/traffic/unblock-all-ips` | Desbloquea todas las IPs bloqueadas.         |
| `GET`  | `/api/traffic/blocked-ips`     | Lista las IPs bloqueadas.                    |

Ejecutar ping entre dos hosts:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src_host": "h169", "dst_host": "h69", "count": 4, "interval": 0.2, "timeout": 10}' \
  http://127.0.0.1:8080/api/traffic/ping
```

Ejecutar `pingall` desde Ryu:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"count": 1, "interval": 0.2, "timeout_per_ping": 5}' \
  http://127.0.0.1:8080/api/traffic/pingall
```

Ejecutar prueba `iperf`:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src_host": "h169", "dst_host": "h69", "duration": 10, "udp": false, "port": 5201}' \
  http://127.0.0.1:8080/api/traffic/iperf
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

Desbloquear todas las IPs:

```bash
curl -X POST \
  -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/traffic/unblock-all-ips
```

Consultar IPs bloqueadas:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/traffic/blocked-ips
```

### Endpoints de enlaces en Ryu

| Método | Endpoint               | Descripción                                           |
| ------ | ---------------------- | ----------------------------------------------------- |
| `POST` | `/api/links/disable`   | Deshabilita un enlace lógico entre dos nodos.         |
| `POST` | `/api/links/enable`    | Habilita un enlace lógico entre dos nodos.            |
| `POST` | `/api/links/loss`      | Aplica pérdida de paquetes a un enlace.               |
| `POST` | `/api/links/bandwidth` | Limita el ancho de banda de un enlace.                |
| `POST` | `/api/links/delay`     | Aplica retardo a un enlace.                           |
| `POST` | `/api/links/tc/clear`  | Limpia la configuración `tc` de un enlace.            |
| `POST` | `/api/links/forget`    | Elimina un enlace del estado interno del controlador. |

Deshabilitar un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5"}' \
  http://127.0.0.1:8080/api/links/disable
```

Habilitar un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5"}' \
  http://127.0.0.1:8080/api/links/enable
```

Aplicar pérdida a un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5", "loss": 10}' \
  http://127.0.0.1:8080/api/links/loss
```

Limitar ancho de banda de un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5", "bandwidth": 10}' \
  http://127.0.0.1:8080/api/links/bandwidth
```

Aplicar retardo a un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5", "delay": "50ms"}' \
  http://127.0.0.1:8080/api/links/delay
```

Limpiar configuración `tc` de un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"src": "s1", "dst": "s5"}' \
  http://127.0.0.1:8080/api/links/tc/clear
```

### Endpoints de puertos en Ryu

| Método | Endpoint               | Descripción                                |
| ------ | ---------------------- | ------------------------------------------ |
| `POST` | `/api/ports/disable`   | Deshabilita un puerto de un switch.        |
| `POST` | `/api/ports/enable`    | Habilita un puerto de un switch.           |
| `POST` | `/api/ports/loss`      | Aplica pérdida de paquetes a un puerto.    |
| `POST` | `/api/ports/bandwidth` | Limita el ancho de banda de un puerto.     |
| `POST` | `/api/ports/delay`     | Aplica retardo a un puerto.                |
| `POST` | `/api/ports/tc/clear`  | Limpia la configuración `tc` de un puerto. |

Deshabilitar un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"dpid": "0000000000000001", "port_no": 2}' \
  http://127.0.0.1:8080/api/ports/disable
```

Habilitar un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"dpid": "0000000000000001", "port_no": 2}' \
  http://127.0.0.1:8080/api/ports/enable
```

Aplicar pérdida a un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"port": "s1-eth2", "loss": 10}' \
  http://127.0.0.1:8080/api/ports/loss
```

Limitar ancho de banda de un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"port": "s1-eth2", "bandwidth": 10}' \
  http://127.0.0.1:8080/api/ports/bandwidth
```

Aplicar retardo a un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"port": "s1-eth2", "delay": "50ms"}' \
  http://127.0.0.1:8080/api/ports/delay
```

Limpiar configuración `tc` de un puerto:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"port": "s1-eth2"}' \
  http://127.0.0.1:8080/api/ports/tc/clear
```

### Endpoints de hosts en Ryu

| Método   | Endpoint                  | Descripción                                                          |
| -------- | ------------------------- | -------------------------------------------------------------------- |
| `POST`   | `/api/hosts/link/attach`  | Notifica al controlador que un host se ha conectado a un switch.     |
| `POST`   | `/api/hosts/link/detach`  | Notifica al controlador que un host se ha desconectado de un switch. |
| `DELETE` | `/api/hosts/forget/{mac}` | Elimina un host del estado interno del controlador usando su MAC.    |

Ejemplo para olvidar un host por MAC:

```bash
curl -X DELETE \
  -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/hosts/forget/00:00:00:00:00:a9
```

## API Mininet

La **API Mininet** se ejecuta por defecto en:

```text
http://127.0.0.1:8081
```

Esta API controla directamente la red emulada en Mininet. Permite consultar el estado de la red, exportar la topología actual, crear hosts, crear switches, crear enlaces, eliminar nodos, eliminar enlaces, aplicar una topología completa y limpiar la topología activa.

A diferencia de la API Ryu, esta API no representa el estado lógico del controlador, sino el estado real de la emulación en Mininet.

### Endpoints de estado y exportación

| Método | Endpoint                       | Descripción                                                                 |
| ------ | ------------------------------ | --------------------------------------------------------------------------- |
| `GET`  | `/api/mininet/status`          | Devuelve el estado actual de Mininet: hosts, switches, enlaces y topología. |
| `GET`  | `/api/mininet/topology/export` | Exporta la topología actual desde Mininet.                                  |

Consultar estado de Mininet:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/status
```

Exportar topología desde Mininet:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/topology/export
```

### Endpoints de creación de nodos

| Método | Endpoint                | Descripción                |
| ------ | ----------------------- | -------------------------- |
| `POST` | `/api/mininet/hosts`    | Crea un host en Mininet.   |
| `POST` | `/api/mininet/switches` | Crea un switch en Mininet. |

Crear un host:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"name": "h10", "ip": "10.0.0.10/24", "mac": "00:00:00:00:00:10", "switch": "s1"}' \
  http://127.0.0.1:8081/api/mininet/hosts
```

Crear un switch:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"name": "s10", "dpid": "10", "protocols": "OpenFlow13"}' \
  http://127.0.0.1:8081/api/mininet/switches
```

### Endpoints de enlaces

| Método   | Endpoint                    | Descripción                                                        |
| -------- | --------------------------- | ------------------------------------------------------------------ |
| `POST`   | `/api/mininet/links`        | Crea un enlace entre dos nodos.                                    |
| `POST`   | `/api/mininet/links/add`    | Crea un enlace entre dos nodos.                                    |
| `POST`   | `/api/mininet/links/delete` | Elimina un enlace entre dos nodos.                                 |
| `DELETE` | `/api/mininet/links`        | Elimina un enlace entre dos nodos usando el cuerpo de la petición. |
| `DELETE` | `/api/mininet/links/delete` | Elimina un enlace entre dos nodos usando el cuerpo de la petición. |

Crear un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"node1": "s1", "node2": "s5"}' \
  http://127.0.0.1:8081/api/mininet/links
```

Crear un enlace indicando puertos:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"node1": "s1", "node2": "s5", "port1": 3, "port2": 3}' \
  http://127.0.0.1:8081/api/mininet/links/add
```

Eliminar un enlace:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"node1": "s1", "node2": "s5"}' \
  http://127.0.0.1:8081/api/mininet/links/delete
```

Eliminar un enlace con `DELETE`:

```bash
curl -X DELETE \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"node1": "s1", "node2": "s5"}' \
  http://127.0.0.1:8081/api/mininet/links
```

### Endpoints de eliminación de nodos

| Método   | Endpoint                       | Descripción                   |
| -------- | ------------------------------ | ----------------------------- |
| `DELETE` | `/api/mininet/hosts/{name}`    | Elimina un host por nombre.   |
| `DELETE` | `/api/mininet/switches/{name}` | Elimina un switch por nombre. |

Eliminar un host:

```bash
curl -X DELETE \
  -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/hosts/h10
```

Eliminar un switch:

```bash
curl -X DELETE \
  -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/switches/s10
```

### Endpoints de topología completa

| Método | Endpoint                      | Descripción                               |
| ------ | ----------------------------- | ----------------------------------------- |
| `POST` | `/api/mininet/topology/apply` | Aplica una topología completa en Mininet. |
| `POST` | `/api/mininet/topology/clear` | Limpia la topología actual de Mininet.    |

Aplicar una topología:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8081/api/mininet/topology/apply
```

Limpiar la topología actual:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"notify_ryu": true}' \
  http://127.0.0.1:8081/api/mininet/topology/clear
```

El parámetro `notify_ryu` indica si Mininet debe avisar al controlador Ryu de los cambios realizados al limpiar la topología.

### Endpoint de pruebas en Mininet

| Método | Endpoint               | Descripción                          |
| ------ | ---------------------- | ------------------------------------ |
| `POST` | `/api/mininet/pingall` | Ejecuta `pingall` dentro de Mininet. |

Ejemplo:

```bash
curl -X POST \
  -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/pingall
```

## Diferencias entre API Ryu y API Mininet

| Aspecto                 | API Ryu                                       | API Mininet                                         |
| ----------------------- | --------------------------------------------- | --------------------------------------------------- |
| Puerto por defecto      | `8080`                                        | `8081`                                              |
| Componente que controla | Controlador SDN                               | Red emulada                                         |
| Estado principal        | Topología descubierta, flujos, STP, políticas | Hosts, switches y enlaces reales en Mininet         |
| Uso principal           | Consultar y modificar el comportamiento SDN   | Crear, borrar o modificar elementos en la emulación |
| Ejemplo                 | Bloquear una IP                               | Crear un host nuevo                                 |
| Endpoint base           | `/api/...`                                    | `/api/mininet/...`                                  |

Ejemplo práctico:

* Si quieres ver qué ha descubierto el controlador, usa `/api/topology` en Ryu.
* Si quieres crear un host nuevo en la red emulada, usa `/api/mininet/hosts` en Mininet.
* Si quieres bloquear una IP, usa `/api/traffic/block-ip` en Ryu.
* Si quieres borrar un switch de la emulación, usa `/api/mininet/switches/{name}` en Mininet.

## Escenarios JSON

La carpeta `scenarios/` contiene escenarios que pueden utilizarse para probar cambios en la topología, estados degradados o configuraciones con STP.

Un escenario puede usarse de dos formas:

1. Con la API Ryu, para validar o importar una topología en el controlador.
2. Con la API Mininet, para aplicar la topología directamente sobre la red emulada.

Validar una topología en Ryu:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/validate
```

Importar una topología en Ryu:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8080/api/topology/import
```

Aplicar una topología en Mininet:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  --data @scenarios/simple_topo.json \
  http://127.0.0.1:8081/api/mininet/topology/apply
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

## Parámetros del runner de Mininet

El archivo `mininet_runner_api.py` permite levantar una topología y activar la API auxiliar de Mininet.

Parámetros principales:

| Parámetro           | Descripción                                     | Valor por defecto       |
| ------------------- | ----------------------------------------------- | ----------------------- |
| `--module`          | Módulo Python donde está definida la topología. | Obligatorio             |
| `--topo`            | Nombre de la clase de la topología.             | Obligatorio             |
| `--controller-ip`   | IP del controlador Ryu.                         | `127.0.0.1`             |
| `--controller-port` | Puerto OpenFlow del controlador.                | `6653`                  |
| `--api-host`        | Dirección donde escucha la API Mininet.         | `0.0.0.0`               |
| `--api-port`        | Puerto de la API Mininet.                       | `8081`                  |
| `--ryu-api-url`     | URL de la API Ryu.                              | `http://127.0.0.1:8080` |
| `--disable-api`     | Desactiva la API auxiliar de Mininet.           | Desactivado             |
| `--skip-clean`      | Evita limpieza previa.                          | Desactivado             |
| `--skip-pingall`    | Evita ejecutar `pingall` inicial.               | Desactivado             |

Ejemplo completo:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.simple_topo \
  --topo SimpleTopo \
  --controller-ip 127.0.0.1 \
  --controller-port 6653 \
  --api-host 0.0.0.0 \
  --api-port 8081 \
  --ryu-api-url http://127.0.0.1:8080
```

## Flujo recomendado de trabajo

1. Limpiar Mininet:

```bash
sudo mn -c
```

2. Iniciar Ryu con descubrimiento de enlaces:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

3. Levantar Mininet con `mininet_runner_api.py`:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.simple_topo \
  --topo SimpleTopo \
  --controller-ip 127.0.0.1 \
  --controller-port 6653 \
  --api-port 8081 \
  --ryu-api-url http://127.0.0.1:8080
```

4. Comprobar que Ryu descubre la topología:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/topology
```

5. Comprobar que Mininet está activo:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/status
```

6. Ejecutar pruebas de tráfico:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"count": 1, "interval": 0.2, "timeout_per_ping": 5}' \
  http://127.0.0.1:8080/api/traffic/pingall
```

7. Probar cambios de topología usando la API Mininet.

8. Revisar STP, métricas de salud y flujos desde la API Ryu.

9. Salir de la CLI de Mininet y limpiar:

```bash
exit
sudo mn -c
```

## Solución de problemas

### La API devuelve `No autorizado`

Comprueba que estás enviando la cabecera:

```bash
-H "X-API-Key: $NETWORK_API_KEY"
```

Y que la variable está definida en la terminal donde ejecutas Ryu y Mininet:

```bash
echo $NETWORK_API_KEY
```

Si ejecutas Ryu y Mininet en terminales distintas, define `NETWORK_API_KEY` en ambas.

### Mininet no conecta con Ryu

Comprueba que Ryu está escuchando antes de arrancar Mininet y que el puerto coincide:

```bash
--controller-ip 127.0.0.1
--controller-port 6653
```

También comprueba que Ryu está iniciado:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

### No aparecen enlaces en la topología

Ejecuta Ryu con:

```bash
ryu-manager --observe-links sdn_api/controller_api.py
```

Sin `--observe-links`, Ryu puede no descubrir los enlaces correctamente.

### No responde la API Ryu

Comprueba que el controlador está levantado y que la API Ryu está disponible en:

```text
http://127.0.0.1:8080
```

Prueba:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8080/api/controller/status
```

### No responde la API Mininet

Comprueba que has arrancado Mininet con el runner `mininet_runner_api.py` y que no has usado `--disable-api`.

La API Mininet debería estar disponible en:

```text
http://127.0.0.1:8081
```

Prueba:

```bash
curl -H "X-API-Key: $NETWORK_API_KEY" \
  http://127.0.0.1:8081/api/mininet/status
```

### El puerto 8080 o 8081 está ocupado

Puedes cambiar el puerto de la API Mininet con:

```bash
sudo python3 mininet_runner_api.py \
  --module topologies.simple_topo \
  --topo SimpleTopo \
  --api-port 8082
```

Para Ryu, revisa la configuración del servidor WSGI de Ryu o libera el puerto ocupado.

### Quedan interfaces antiguas de Mininet

Limpia el entorno:

```bash
sudo mn -c
```

### Un host o switch no se crea

Comprueba que el nombre no exista ya en Mininet. Los nombres deben empezar por una letra y pueden contener letras, números, guiones y guiones bajos.

Ejemplo válido:

```text
h10
s10
host_test
switch-1
```

### Un enlace no se elimina

Comprueba que los nodos existen y que el enlace indicado realmente está creado. Si hay varios enlaces entre los mismos nodos, indica también los puertos:

```bash
curl -X DELETE \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NETWORK_API_KEY" \
  -d '{"node1": "s1", "node2": "s5", "port1": 2, "port2": 2}' \
  http://127.0.0.1:8081/api/mininet/links
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

Para añadir nuevas rutas REST en Ryu:

1. Modifica o amplía los servicios dentro de `sdn_api/`.
2. Registra la ruta correspondiente en `sdn_api/rest_routes.py`.
3. Añade la lógica necesaria en el controlador o servicio correspondiente.
4. Prueba el endpoint con `curl`.

Para añadir nuevas rutas REST en Mininet:

1. Modifica los servicios dentro de `mininet_live_api/`.
2. Añade la ruta en `mininet_live_api/http_server.py`.
3. Implementa la acción sobre la red emulada.
4. Comprueba que la API responde desde el puerto configurado con `--api-port`.

## Resumen de endpoints

### API Ryu

| Método   | Endpoint                        |
| -------- | ------------------------------- |
| `GET`    | `/api/topology`                 |
| `GET`    | `/api/topology/export`          |
| `POST`   | `/api/topology/validate`        |
| `POST`   | `/api/topology/import`          |
| `POST`   | `/api/controller/runtime/reset` |
| `GET`    | `/api/controller/status`        |
| `GET`    | `/api/health`                   |
| `GET`    | `/api/health/summary`           |
| `GET`    | `/api/switch/{dpid}/ports`      |
| `GET`    | `/api/switch/{dpid}/flows`      |
| `GET`    | `/api/stp/status`               |
| `POST`   | `/api/traffic/ping`             |
| `POST`   | `/api/traffic/pingall`          |
| `POST`   | `/api/traffic/iperf`            |
| `POST`   | `/api/traffic/block-ip`         |
| `POST`   | `/api/traffic/unblock-ip`       |
| `POST`   | `/api/traffic/unblock-all-ips`  |
| `GET`    | `/api/traffic/blocked-ips`      |
| `POST`   | `/api/links/disable`            |
| `POST`   | `/api/links/enable`             |
| `POST`   | `/api/links/loss`               |
| `POST`   | `/api/links/bandwidth`          |
| `POST`   | `/api/links/delay`              |
| `POST`   | `/api/links/tc/clear`           |
| `POST`   | `/api/links/forget`             |
| `POST`   | `/api/ports/disable`            |
| `POST`   | `/api/ports/enable`             |
| `POST`   | `/api/ports/loss`               |
| `POST`   | `/api/ports/bandwidth`          |
| `POST`   | `/api/ports/delay`              |
| `POST`   | `/api/ports/tc/clear`           |
| `POST`   | `/api/hosts/link/attach`        |
| `POST`   | `/api/hosts/link/detach`        |
| `DELETE` | `/api/hosts/forget/{mac}`       |

### API Mininet

| Método   | Endpoint                       |
| -------- | ------------------------------ |
| `GET`    | `/api/mininet/status`          |
| `GET`    | `/api/mininet/topology/export` |
| `POST`   | `/api/mininet/hosts`           |
| `POST`   | `/api/mininet/switches`        |
| `POST`   | `/api/mininet/links`           |
| `POST`   | `/api/mininet/links/add`       |
| `POST`   | `/api/mininet/links/delete`    |
| `DELETE` | `/api/mininet/links`           |
| `DELETE` | `/api/mininet/links/delete`    |
| `DELETE` | `/api/mininet/hosts/{name}`    |
| `DELETE` | `/api/mininet/switches/{name}` |
| `POST`   | `/api/mininet/topology/apply`  |
| `POST`   | `/api/mininet/topology/clear`  |
| `POST`   | `/api/mininet/pingall`         |

