package defaultImplementations.inputLines;

import framework.CheckerInterface;

/**
 * Implementation of {@link framework.CheckerInterface#inputLines(String)}
 *
 * Use this if the input consists of a single line.
 *
 * @author Philipp Hoffmann
 *
 */
public interface SingleLineInput extends CheckerInterface {
	/**
	 * Always returns 0. Use this if the input consists of a single line.
	 */
	@Override
	default int inputLines(String firstLine) {
		return 0;
	}
}
