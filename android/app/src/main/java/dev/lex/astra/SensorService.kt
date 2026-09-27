package dev.lex.astra

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.IBinder
import androidx.core.app.NotificationCompat

class SensorService : Service(), SensorEventListener {
    private lateinit var sensors: SensorManager
    private lateinit var repo: MeshRepository
    private var lastAccelerometer = 0L
    private var lastGyro = 0L
    private var lastRotation = 0L

    override fun onCreate() {
        super.onCreate()
        repo = MeshRepository.get(this)
        sensors = getSystemService(SENSOR_SERVICE) as SensorManager
        createChannel()

        startForeground(
            80,
            NotificationCompat.Builder(this, CHANNEL)
                .setContentTitle("Astra Mesh")
                .setContentText("Sensores conectados ao seu Astra")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setOngoing(true)
                .build()
        )

        sensors.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let {
            sensors.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
        sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            sensors.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
        sensors.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)?.let {
            sensors.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
    }

    override fun onDestroy() {
        sensors.unregisterListener(this)
        super.onDestroy()
    }

    override fun onSensorChanged(event: SensorEvent) {
        val now = System.nanoTime()
        val previous = when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> lastAccelerometer
            Sensor.TYPE_GYROSCOPE -> lastGyro
            Sensor.TYPE_ROTATION_VECTOR -> lastRotation
            else -> 0L
        }
        if (previous != 0L && now - previous < 50_000_000L) return

        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                lastAccelerometer = now
                repo.sendSensor("accelerometer", event.values.copyOf(3), event.timestamp)
            }
            Sensor.TYPE_GYROSCOPE -> {
                lastGyro = now
                repo.sendSensor("gyroscope", event.values.copyOf(3), event.timestamp)
            }
            Sensor.TYPE_ROTATION_VECTOR -> {
                lastRotation = now
                repo.sendSensor(
                    "rotation_vector",
                    event.values.copyOf(minOf(5, event.values.size)),
                    event.timestamp
                )
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL,
                "Astra Mesh",
                NotificationManager.IMPORTANCE_LOW
            )
        )
    }

    companion object {
        const val CHANNEL = "astra_mesh"
    }
}
