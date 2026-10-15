import org.apache.spark.sql.SparkSession
import org.apache.spark.sql.functions._
import org.apache.spark.ml.feature.VectorAssembler
import org.apache.spark.ml.classification.RandomForestClassifier
import org.apache.spark.ml.evaluation.MulticlassClassificationEvaluator
import scala.util.Try

object BDAProjectTrain {
  def main(args: Array[String]): Unit = {
    val spark = SparkSession.builder().appName("BDAProjectTrain").getOrCreate()
    spark.conf.set("spark.sql.files.ignoreCorruptFiles", "true")
    import spark.implicits._
    spark.sparkContext.setLogLevel("WARN")

    // --- Clean raw weather data ---
    val rawLines = spark.read.textFile("hdfs://namenode:9000/bda_project/raw/weather/*.gz")

    val parsed = rawLines.flatMap { line =>
      Try {
        val usaf = line.substring(4, 10)
        val date = line.substring(15, 23)
        val lat = line.substring(28, 34).toDouble / 1000.0
        val lon = line.substring(34, 41).toDouble / 1000.0
        val windRaw = line.substring(65, 69)
        val tempRaw = line.substring(87, 92)
        val dewRaw = line.substring(93, 98)
        val wind = if (windRaw == "9999") None else Some(windRaw.toDouble / 10.0)
        val temp = if (tempRaw == "+9999") None else Some(tempRaw.toDouble / 10.0)
        val dew = if (dewRaw == "+9999") None else Some(dewRaw.toDouble / 10.0)
        (usaf, date, lat, lon, wind, temp, dew)
      }.toOption
    }.toDF("station_id", "date", "latitude", "longitude", "wind_speed", "temperature", "dew_point")

    val cleaned = parsed.filter($"temperature".isNotNull && $"wind_speed".isNotNull)

    // --- Label + features ---
    val labeled = cleaned.withColumn(
      "fire_risk",
      when($"temperature" > 28 && $"wind_speed" > 5, 1).otherwise(0)
    )

    val assembler = new VectorAssembler()
      .setInputCols(Array("temperature", "wind_speed"))
      .setOutputCol("features")
      .setHandleInvalid("skip")

    val featureDF = assembler.transform(labeled)
    val Array(trainDF, testDF) = featureDF.randomSplit(Array(0.8, 0.2), seed = 42)

    // --- Train ---
    val rf = new RandomForestClassifier()
      .setLabelCol("fire_risk")
      .setFeaturesCol("features")
      .setNumTrees(50)

    val model = rf.fit(trainDF)
    val predictions = model.transform(testDF)

    // --- Evaluate ---
    val evaluator = new MulticlassClassificationEvaluator()
      .setLabelCol("fire_risk").setPredictionCol("prediction")

    val f1 = evaluator.setMetricName("f1").evaluate(predictions)
    val precision = evaluator.setMetricName("weightedPrecision").evaluate(predictions)
    val recall = evaluator.setMetricName("weightedRecall").evaluate(predictions)

    println("=== MODEL RESULTS ===")
    println(s"F1 Score: $f1")
    println(s"Precision: $precision")
    println(s"Recall: $recall")

    predictions.select("station_id", "date", "temperature", "wind_speed", "fire_risk", "prediction")
      .write.mode("overwrite").option("header", "true")
      .csv("file:///app/output/predictions")

    spark.stop()
  }
}