# opc_mitsu

Gateway **PLC Mitsubishi** (protokol MC / MELSEC) yang membaca/menulis tag via Ethernet,
menyinkronkan datanya ke **database MySQL/MariaDB**, dan menyediakan antarmuka **GUI modern** berbasis PyQt6.

```
 ┌────────────┐   Ethernet MC    ┌──────────────┐    MySQL     ┌──────────────┐
 │ PLC        │  (pymcprotocol)  │  opc_mitsu   │  (PyMySQL)   │ MySQL/MariaDB│
 │ Mitsubishi │◄────────────────►│   Gateway    │◄────────────►│  t_reg_status│
 │ Q/L/iQ-R   │                  │  - Poller    │              │  t_transmit  │
 └────────────┘                  │  - GUI       │              └──────────────┘
                                 └──────────────┘
```

## Fitur

- **Komunikasi PLC via driver multi-brand** — pilih lewat `plc.driver` di `config.yaml`:
  - `mitsubishi` — MC Protocol Ethernet via `pymcprotocol` (Q/L/QnA/iQ-L/iQ-R).
  - `modbus_tcp` — Modbus TCP (Schneider, Delta, LS, Inovance, Wago, dll).
  - `modbus_rtu` — Modbus RTU serial RS-485 (via `pyserial`).
  - `omron_fins` — Omron FINS TCP (NJ/NX, CP/CJ).
- **Sinkronisasi database MySQL/MariaDB** dengan writer thread + queue sehingga PLC tidak pernah diblok DB:
  - **`t_reg_status`** — mirror nilai register PLC (upsert 1 baris per tag).
  - **`t_transmit`** — antrian perintah tulis dari luar; gateway menulis ke PLC lalu **menghapus baris** setelah sukses.
- **GUI modern** (PyQt6, tema gelap) dengan 3 halaman:
  - **Task** — memantau nilai tag secara live (Read Data) dan menulis nilai (Write Data).
  - **Setup** — mengatur koneksi PLC, database, dan aplikasi.
  - **Logs** — log real-time.
- **Daftar TAG_NAME (address space)** didefinisikan di `config.yaml` (`tags:`) — seperti *server project* pada OPC:
  - Setiap tag: `name`, `address`, `type`, `writable`, `scale`, `offset`, `swap_words`.
  - **Server (gateway) adalah pemilik daftar tag**; client (GUI/MySQL) hanya baca/tulis lewat **nama tag**.
  - `t_reg_status` hanyalah **cermin nilai** (upsert 1 baris per tag) — bukan sumber definisi tag.
  - Menambah/mengubah/menghapus tag = edit `config.yaml`, lalu restart gateway (atau "Muat Ulang dari config.yaml" di halaman Task).
- Bila PLC **tidak terhubung**, aplikasi menampilkan status **PLC Disconnect** dan data register kosong (`CONNECT_STAT='0'`).

## Instalasi

Pratinjau: Python 3.10+ (diuji pada 3.13).

```powershell
pip install -r requirements.txt
```

Isi `requirements.txt`: `PyQt6`, `pymcprotocol`, `PyMySQL`, `PyYAML`.

## Menjalankan

```powershell
python main.py                # pakai config.yaml di folder ini
python main.py --config lain.yaml
```

Database MySQL dibuat otomatis (`create_schema: true`) saat pertama terhubung.
Schema yang dibuat:

```sql
CREATE DATABASE IF NOT EXISTS `opc_mitsu` CHARACTER SET latin1 COLLATE latin1_swedish_ci;

-- Baca: mirror nilai PLC (upsert per DEV_NAME + TAG_NAME)
CREATE TABLE IF NOT EXISTS `opc_mitsu`.`t_reg_status` (
    CLIENT_HDL   INT(11)      NOT NULL AUTO_INCREMENT,
    DEV_NAME     VARCHAR(30)  NOT NULL DEFAULT 'MITSUBISHI',
    GROUP_NAME   VARCHAR(30)  NOT NULL,
    TAG_NAME     VARCHAR(50)  NOT NULL DEFAULT '',
    REG_VALUE    VARCHAR(50)  DEFAULT NULL,
    TR_TIME      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    CONNECT_STAT CHAR(1)      DEFAULT '1',
    PRIMARY KEY (CLIENT_HDL) USING BTREE,
    UNIQUE KEY uk_dev_tag (DEV_NAME, TAG_NAME),
    INDEX idx_group (GROUP_NAME)
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci ROW_FORMAT=DYNAMIC;

-- Tulis: antrian perintah dari luar -> ditulis ke PLC -> baris dihapus
CREATE TABLE IF NOT EXISTS `opc_mitsu`.`t_transmit` (
    ID        INT(11)               NOT NULL AUTO_INCREMENT,
    DEV_NAME  VARCHAR(100)          DEFAULT NULL,
    REG_NAME  VARCHAR(100)          DEFAULT NULL,
    REG_VALUE VARCHAR(50)           DEFAULT NULL,
    TTL       SMALLINT(5) UNSIGNED  DEFAULT NULL,
    TR_TIME   DATETIME              DEFAULT NULL,
    PRIMARY KEY (ID)
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;
```

> Kolom `uk_dev_tag` (unique) pada `t_reg_status` dan kolom `ID` (auto-increment) pada `t_transmit`
> ditambahkan otomatis bila tabel sudah ada (migrasi). Keduanya murni penambahan, tidak mengubah kolom asal.

## Cara menulis ke PLC lewat database

Sisipkan satu baris ke `t_transmit`, lalu gateway (polling) akan menuliskan nilainya ke PLC
dan menghapus baris tersebut setelah berhasil:

```sql
INSERT INTO opc_mitsu.t_transmit (DEV_NAME, REG_NAME, REG_VALUE, TTL, TR_TIME)
VALUES ('MITSUBISHI', 'D100', '1234', 10, NOW());
```

- `REG_NAME` dicocokkan dengan **nama tag** atau **alamat** (mis. `D100`) — tidak peka huruf besar/kecil.
- Tag harus `writable: true`; kalau tidak, baris dihapus tanpa menulis.
- Bila penulisan gagal, baris **dibiarkan** sehingga dicoba lagi pada polling berikutnya.
- `TTL` hanya informasional (tidak dipakai) karena baris dihapus setelah sukses.

## Mengelola daftar tag (TAG_NAME)

Tag adalah *address space* milik server (gateway), didefinisikan di `config.yaml` (`tags:`), persis
seperti tag/point pada OPC server. Client (GUI, MySQL) hanya membaca/menulis berdasarkan **nama tag**.

- **Tambah / ubah / hapus tag** → edit bagian `tags:` di `config.yaml`.
- **Terapkan** tanpa restart → tombol **Muat Ulang dari config.yaml** di halaman Task, atau restart gateway.
- `t_reg_status` otomatis mengikuti daftar tag (cermin nilai, upsert per tag); baris lama untuk tag yang
  sudah dihapus tidak lagi diperbarui.

## Konfigurasi (`config.yaml`)

| Bagian | Kunci penting | Keterangan |
| --- | --- | --- |
| `app` | `log_level`, `log_dir` | level log & folder file log |
| `plc` | `driver`, `ip`, `port`, `poll_interval`, `auto_reconnect` | driver PLC + koneksi dasar (semua driver) |
| `plc` | `protocol`, `plctype`, `network`, `pc`, `dest_moduleio`, `dest_modulesta` | khusus driver `mitsubishi` (MC Protocol) |
| `plc` | `unit_id`, `serial_port`, `baudrate`, `parity`, `stopbits` | khusus Modbus (`unit_id` juga dipakai RTU/TCP) |
| `plc` | `fins_network` (DNA), `fins_node` (DA1), `fins_unit` (DA2) | khusus driver `omron_fins` |
| `database` | `enabled`, `host/port/user/password/database`, `status_table`, `transmit_table`, `dev_name`, `group_name`, `write_from_db`, `create_schema` | MySQL + tabel baca/tulis |
| `tags` | `name`, `address`, `type`, `writable`, `scale`, `offset`, `swap_words` | daftar tag (address space) |

### Alamat tag per driver

| Driver | Contoh alamat | Keterangan |
| --- | --- | --- |
| `mitsubishi` | `D100`, `M100`, `X0`, `Y10`, `W0`, `R10` | device MC Protocol (huruf depan = jenis device) |
| `modbus_tcp` / `modbus_rtu` | `C10` (coil), `DI10` (discrete input), `HR100` (holding reg), `IR100` (input reg) | `C`/`DI` untuk tipe `bit`; `HR`/`IR` untuk tipe word |
| `omron_fins` | `D100` (DM), `C100` (CIO), `W100` (WR), `H100` (HR), `A100` (AR) | tambah `.n` untuk bit, mis. `C100.5`; tag `bit` tanpa `.n` = bit 0 |

- Nilai 32-bit menempati 2 register/word berturut-turut (high word dulu); pakai `swap_words: true`
  bila urutan word terbalik di perangkat Anda.

### Tipe tag

| `type` | Device contoh | Lebar | Catatan |
| --- | --- | --- | --- |
| `bit` | `M100`, `X0`, `Y10` | 1 bit | ON/OFF |
| `int16` | `D100` | 1 word | signed |
| `uint16` | `D100` | 1 word | unsigned |
| `int32` | `D100` | 2 word | signed |
| `uint32` | `D100` | 2 word | unsigned |
| `float32` | `D100` | 2 word | IEEE-754; pakai `swap_words: true` bila urutan word terbalik |

- `scale` / `offset`: nilai yang dibaca/ditulis = `raw * scale + offset` (nilai engineering).
- `writable: true`: tag boleh ditulis dari GUI maupun dari perintah `t_transmit` di database.

## Sisi PLC (GX Works / GX Works2/3)

Bagian ini khusus driver `mitsubishi`. Aktifkan komunikasi Ethernet MC protocol:

1. **Parameter PLC** → **Built-in Ethernet Port Setting** (atau modul Ethernet/CC-Link IE).
2. **Open Setting** → buat **UDP/TCP** connection, isi protocol `TCP`, **MC Protocol**, port `5000`.
3. Sesuaikan **Network No / Station No** dengan `plc.network` / `plc.pc` di `config.yaml`
   (default `network: 0`, `pc: 255` untuk koneksi langsung).
4. Isi `plc.ip`/`plc.port` di `config.yaml` sesuai PLC, lalu jalankan aplikasi.

## Struktur proyek

```
opc_mitsu/
├── main.py               # entry point + argumen CLI
├── config.yaml           # konfigurasi
├── requirements.txt
├── app/
│   ├── config.py         # dataclass + load/save YAML
│   ├── logging_setup.py  # logging + handler GUI
│   ├── store.py          # cache tag & status (thread-safe)
│   ├── plc_client.py     # base + driver Mitsubishi (MC protocol)
│   ├── modbus_client.py  # driver Modbus TCP & RTU
│   ├── fins_client.py    # driver Omron FINS TCP
│   ├── database.py       # MySQL writer thread
│   ├── gateway.py        # orkestrasi poller
│   └── gui/
│       ├── theme.py      # QSS tema gelap
│       ├── widgets.py    # kartu status, badge, trend chart
│       ├── main_window.py
│       ├── tags_page.py
│       ├── settings_page.py
│       └── logs_page.py
└── logs/                 # file log (dibuat otomatis)
```

## Troubleshooting

- **PLC timeout / tidak terhubung** → titik status **PLC** di header berwarna merah dan `t_reg_status` bernilai `NULL` dengan `CONNECT_STAT='0'`.
  Cek IP & port, pastikan Open Setting MC Protocol aktif, coba protokol `binary` vs `ascii`, dan `plctype` yang benar.
  Gateway mencoba menyambung ulang otomatis bila `auto_reconnect: true`.
- **Nilai float32 salah** → coba `swap_words: true` pada tag tersebut.
- **Database terputus** → gateway tetap berjalan; data tertahan di queue dan dicoba lagi otomatis.
  Periksa pengaturan koneksi database di halaman **Setup**.
