import org.apache.spark.sql.{DataFrame, Row, SparkSession}
import org.apache.spark.sql.types._
import org.apache.spark.sql.functions._
import org.apache.spark.sql.streaming.Trigger
import scala.collection.mutable

object BDAProjectStream {
  def main(args: Array[String]): Unit = {
    val spark = SparkSession.builder()
      .appName("BDAProjectStream")
      .getOrCreate()

    import spark.implicits._
    spark.sparkContext.setLogLevel("WARN")

    val HDFS = "hdfs://namenode:9000/bda_project"

    // ---------------- Schemas (sensor values and social geotag may be missing) ----------------
    val rawWeatherSchema = new StructType()
      .add("station_id", StringType).add("lat", DoubleType).add("lon", DoubleType)
      .add("temperature", DoubleType).add("wind_speed", DoubleType)
      .add("humidity", DoubleType).add("timestamp", TimestampType)

    val filledWeatherSchema = rawWeatherSchema.add("gap_filled", StringType)

    val socialSchema = new StructType()
      .add("post_id", StringType).add("text", StringType)
      .add("lat", DoubleType).add("lon", DoubleType)
      .add("timestamp", TimestampType).add("is_fire_related", BooleanType)

    // ---------------- STEP 1: fill missing sensor values with the last known value ----------------
    type Sensors = (Option[Double], Option[Double], Option[Double]) // temp, wind, humidity
    val lastKnown = mutable.Map[String, Sensors]()
    val noHistory: Sensors = (None, None, None)

    def num(r: Row, name: String): Option[Double] = {
      val i = r.fieldIndex(name)
      if (r.isNullAt(i)) None else Some(r.getDouble(i))
    }

    val fillBatch: (DataFrame, Long) => Unit = (batch, batchId) => {
      val rows = batch
        .filter($"timestamp".isNotNull && $"station_id".isNotNull && $"lat".isNotNull && $"lon".isNotNull)
        .collect()
        .sortBy(r => r.getAs[java.sql.Timestamp]("timestamp").getTime)

      if (rows.nonEmpty) {
        val filled = rows.map { r =>
          val sid = r.getAs[String]("station_id")
          val (pT, pW, pH) = lastKnown.getOrElse(sid, noHistory)
          val t = num(r, "temperature")
          val w = num(r, "wind_speed")
          val h = num(r, "humidity")
          val tF = t.orElse(pT)
          val wF = w.orElse(pW)
          val hF = h.orElse(pH)
          lastKnown(sid) = (tF, wF, hF)
          val gaps = Seq(
            if (t.isEmpty && tF.isDefined) "temp" else "",
            if (w.isEmpty && wF.isDefined) "wind" else "",
            if (h.isEmpty && hF.isDefined) "humidity" else ""
          ).filter(_.nonEmpty).mkString(",")
          (sid, r.getAs[Double]("lat"), r.getAs[Double]("lon"), tF, wF, hF,
            r.getAs[java.sql.Timestamp]("timestamp"), gaps)
        }

        filled.toSeq
          .toDF("station_id", "lat", "lon", "temperature", "wind_speed", "humidity", "timestamp", "gap_filled")
          .coalesce(1)
          .write.mode("append")
          .json(s"$HDFS/incoming/weather_filled/")

        println(s"[gap-fill] batch $batchId: ${filled.length} readings, ${filled.count(_._8.nonEmpty)} had gaps filled")
      }
    }

    val fillQuery = spark.readStream
      .schema(rawWeatherSchema)
      .json(s"$HDFS/incoming/weather/")
      .writeStream
      .foreachBatch(fillBatch)
      .option("checkpointLocation", "file:///app/checkpoints/weather_fill_v1/")
      .trigger(Trigger.ProcessingTime("5 seconds"))
      .start()

    // ---------------- STEP 2: join social posts with risky weather ----------------
    // Round lat/lon to the nearest 0.1 to create a "grid cell" equality join key
    def gridCell(c: org.apache.spark.sql.Column) = round(c)   // 1-degree cells (~100 km)

    val weatherStream = spark.readStream
      .schema(filledWeatherSchema)
      .json(s"$HDFS/incoming/weather_filled/")
      .withColumn("event_time", $"timestamp")
      .withWatermark("event_time", "2 minutes")
      .withColumn("grid_lat", gridCell($"lat"))
      .withColumn("grid_lon", gridCell($"lon"))

    // Posts without coordinates: recover location from the city name in the text
    val cityLat = when($"text".contains("Los Angeles"), 34.05)
      .when($"text".contains("San Francisco"), 37.77)
      .when($"text".contains("Las Vegas"), 36.16)
    val cityLon = when($"text".contains("Los Angeles"), -118.24)
      .when($"text".contains("San Francisco"), -122.42)
      .when($"text".contains("Las Vegas"), -115.15)

    val socialStream = spark.readStream
      .schema(socialSchema)
      .json(s"$HDFS/incoming/social/")
      .filter($"is_fire_related" === true)
      .withColumn("geo_inferred", $"lat".isNull)
      .withColumn("lat", coalesce($"lat", cityLat))
      .withColumn("lon", coalesce($"lon", cityLon))
      .withColumn("event_time", $"timestamp")
      .withWatermark("event_time", "2 minutes")
      .withColumn("grid_lat", gridCell($"lat"))
      .withColumn("grid_lon", gridCell($"lon"))

    // After gap-filling, a still-missing value is null and simply never counts as risky
    val riskyWeather = weatherStream.filter($"temperature" > 28 && $"wind_speed" > 5)

    val verifiedAlerts = socialStream.as("s")
      .join(
        riskyWeather.as("w"),
        expr("""
          s.grid_lat = w.grid_lat AND
          s.grid_lon = w.grid_lon AND
          s.event_time BETWEEN w.event_time - interval 2 minutes AND w.event_time + interval 2 minutes
        """)
      )
      .select(
        $"s.post_id", $"s.text", $"w.station_id", $"w.lat", $"w.lon",
        $"w.temperature", $"w.wind_speed", $"w.humidity",
        $"w.gap_filled", $"s.geo_inferred", $"s.event_time"
      )

    val consoleQuery = verifiedAlerts.writeStream
      .outputMode("append")
      .format("console")
      .option("truncate", "false")
      .trigger(Trigger.ProcessingTime("10 seconds"))
      .start()

    val fileQuery = verifiedAlerts.writeStream
      .outputMode("append")
      .format("json")
      .option("path", "file:///app/output/alerts/")
      .option("checkpointLocation", "file:///app/checkpoints/alerts_v3/")
      .trigger(Trigger.ProcessingTime("10 seconds"))
      .start()

    spark.streams.awaitAnyTermination()
  }
}